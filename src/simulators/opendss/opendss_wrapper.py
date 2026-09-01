"""Fachada única de acesso ao OpenDSS via ``py_dss_interface``.

O comportamento vive em quatro camadas, compostas aqui por herança para que a
API pública continue plana:

===================================  ==============================================
:class:`~._engine.EngineMixin`       compilar, resolver, invalidar o cache
:class:`~._reader.ReaderMixin`       ler barras, elementos, propriedades, totais
:class:`~._writer.WriterMixin`       escrever potências, propriedades, taps, estado
:class:`~._legacy.LegacyReadsMixin`  leituras polimórficas superadas
===================================  ==============================================

Conforme o ``AGENTS.md``, este wrapper é a única fonte de verdade para
interações com o OpenDSS: os simuladores não devem chamar ``py_dss_interface``
diretamente.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
from dataclasses import asdict

import py_dss_interface

from ._engine import EngineMixin
from ._legacy import LegacyReadsMixin
from ._reader import ReaderMixin
from ._types import (
    LINE_CLASSES,
    ElementSnapshot,
    OpenDSSException,
    SolutionSnapshot,
)
from ._writer import WriterMixin
from .topology_builder import build_graph

__all__ = [
    "LINE_CLASSES",
    "ElementSnapshot",
    "OpenDSS",
    "OpenDSSException",
    "SolutionSnapshot",
]


class OpenDSS(EngineMixin, ReaderMixin, WriterMixin, LegacyReadsMixin):
    """
    Wrapper class to manage the interface with OpenDSS (via py_dss_interface).

    It handles circuit compilation, time flow management, data extraction,
    and element control (Loads, PVs, Storage, etc.).

    Um wrapper atende **um** circuito. Todas as instâncias de
    ``py_dss_interface.DSS()`` compartilham o mesmo motor OpenDSS no processo:
    compilar um segundo circuito repõe o primeiro em silêncio, e os dois
    wrappers passam a ler o mesmo estado. Por isso o construtor recebe um único
    ``topofile`` — arquivos auxiliares do alimentador entram pelos ``Redirect``
    do próprio master.
    """

    name = "DSS"

    def __init__(
        self,
        topofile: str | os.PathLike,
        time_step: dt.timedelta,
        start_time: dt.datetime,
        fail_on_error: bool = True,
        **kwargs: object,
    ):
        """
        Initializes the OpenDSS instance.

        Args:
            topofile (Union[str, os.PathLike]): Path to the master .dss file.
                Exactly one circuit per wrapper — see the note in the class
                docstring; extra feeder files belong in the master's own
                ``Redirect`` lines.
            time_step (dt.timedelta): The simulation time step.
            start_time (dt.datetime): The simulation start time (sets hour and angle).
            fail_on_error (bool, optional): If True, raises an exception on DSS errors. Defaults to True.
            **kwargs: Additional arguments (currently unused).

        Raises:
            TypeError: If a list/tuple of paths is passed (the pre-refactor
                signature accepted one) — only a single circuit is supported.
        """
        if isinstance(topofile, (list, tuple, set)):
            raise TypeError(
                "topofile takes a single .dss file, not a collection of paths. "
                "All DSS() instances share one OpenDSS engine in the process, so "
                "a second circuit would replace the first instead of running "
                "alongside it. Put auxiliary files in the master's Redirect lines."
            )

        # Capturado antes de instanciar o motor: o construtor do
        # py_dss_interface muda o diretorio de trabalho do processo.
        base_dir = pathlib.Path.cwd()

        self.dss = py_dss_interface.DSS()
        self.fail_on_error = fail_on_error
        self._snapshot = SolutionSnapshot()
        self._node_index: dict[str, list[tuple[int, int]]] | None = None

        self.print("Compiling...")
        self.warn_if_engine_already_in_use()
        self.compile_circuit(topofile, base_dir)

        # Checks for the existence of specific elements to optimize data retrieval
        self.includes_elements = {
            "Load": len(self.dss.loads.names) > 0,
            "PVSystem": len(self.dss.pvsystems.names) > 0,
            "Generator": len(self.dss.generators.names) > 0,
        }

        # Specific logic to handle Storage elements
        self.dss.circuit.set_active_class("Storage")
        storages_names = self.dss.active_class.names

        if storages_names and storages_names[0] is not None:
            self.includes_elements["Storage"] = True
            self.storage_names = storages_names
        else:
            self.includes_elements["Storage"] = False
            self.storage_names = []

        self.dss.solution.mode = 0  # Snapshot mode (initialization)
        self.dss.solution.number = 1

        day_of_year = start_time.timetuple().tm_yday - 1
        self.dss.solution.hour = day_of_year * 24 + start_time.hour

        self.dss.solution.step_size = 0
        self.run_dss()
        self.dss.solution.step_size = time_step.total_seconds()

        self.print(f"Compiled Circuit: {self.dss.circuit.name}")

    def grafo_tsdq(self, output_path):
        """
        Exporta o grafo do circuito em formato JSON, incluindo nós e arestas.

        Padrão utilizado na plataforma `tsdq-dataview-opentes`

        """

        grafo = build_graph(self.dss)

        grafo_dict = {
            "nodes": [asdict(node) for node in grafo.nodes.values()],
            "edges": [asdict(edge) for edge in grafo.edges.values()],
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(grafo_dict, f, indent=4, ensure_ascii=False)
