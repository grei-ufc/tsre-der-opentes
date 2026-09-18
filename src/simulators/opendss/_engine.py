"""Ciclo de vida do motor OpenDSS: compilacao, solucao e invalidacao de cache.

Camada mais baixa do wrapper. Detem o handle ``dss``, o cache da solucao e o
tratamento de erros; leitura e escrita se apoiam nela.
"""

from __future__ import annotations

import datetime as dt
import os
import pathlib
from typing import Any

from ._types import OpenDSSException


class EngineMixin:
    """Compilacao, execucao e invalidacao de cache.

    Espera de quem compoe: ``self.dss``, ``self._snapshot``,
    ``self._node_index``, ``self.fail_on_error``, ``self.includes_elements``,
    ``self._tolerance`` e ``self._max_iterations``.
    """

    def warn_if_engine_already_in_use(self) -> None:
        """Avisa se já existe outro circuito compilado no mesmo motor.

        Todas as instâncias de ``py_dss_interface.DSS()`` compartilham **um
        único** motor OpenDSS no processo: compilar um segundo circuito
        repõe o primeiro, e o wrapper anterior passa a ler o circuito novo sem
        qualquer erro. Como isso é invisível, é sinalizado aqui.

        Para de fato isolar dois circuitos, cada um precisa de sua própria cópia
        da DLL (``py_dss_interface.DSS(dll_path)``).
        """
        existing = self.dss.circuit.name
        if existing:
            self.print(
                f"[AVISO] O motor OpenDSS ja tem o circuito '{existing}' compilado. "
                "Todas as instancias DSS() compartilham o mesmo motor, entao o "
                "circuito anterior sera substituido e qualquer wrapper que o use "
                "passara a ler este. Para dois circuitos simultaneos, cada um "
                "precisa de sua propria copia da DLL."
            )

    def compile_circuit(self, topofile: str | os.PathLike, base_dir: pathlib.Path) -> None:
        """Compila o arquivo ``.dss`` do circuito, falhando alto se algo der errado.

        Instanciar ``py_dss_interface.DSS()`` **muda o diretório de trabalho do
        processo** para o ``DataPath`` que o motor guardou — possivelmente de
        outra sessão, até de outro projeto. A partir daí, qualquer caminho
        relativo que o Python resolva (``Path.resolve()``, ``Path.cwd()``) sai
        errado em silêncio, produzindo caminhos duplicados como
        ``.../data/13Bus/data/13Bus/master.dss``. E o ``Redirect`` de um arquivo
        inexistente não levanta erro: a simulação segue com o circuito vazio.

        Daí as três defesas: caminhos relativos são resolvidos contra
        *base_dir* (capturado antes de o motor existir), a existência do
        arquivo é conferida antes do ``Redirect``, e o diretório de trabalho é
        devolvido ao original no fim.

        Args:
            topofile: Caminho do arquivo ``.dss`` master a compilar. É um
                arquivo só: o motor OpenDSS é único no processo (veja
                :meth:`warn_if_engine_already_in_use`), então cada wrapper
                atende a exatamente um circuito. Arquivos auxiliares do
                alimentador entram pelos ``Redirect`` do próprio master.
            base_dir: Diretório contra o qual resolver caminhos relativos.

        Raises:
            OpenDSSException: Se o arquivo não existe, se o ``Redirect``
                reporta erro, ou se ao final o circuito não tem barras.
        """
        try:
            path = pathlib.Path(topofile).expanduser()
            if not path.is_absolute():
                path = (base_dir / path).resolve()

            if not path.is_file():
                self.fail(f'DSS file not found: "{path}"')
                return

            self.dss.text(f"set datapath={path.parent}")
            status = self.dss.text(f'Redirect "{path}"')

            if status and ("not found" in status.lower() or "error" in status.lower()):
                self.fail(f'Redirect failed for "{path}": {status}')

            if self.dss.circuit.num_buses == 0:
                self.fail(
                    f'No circuit was compiled from "{path}". The circuit has no '
                    "buses — check the file path and its contents."
                )

            self.apply_solution_settings()
        finally:
            os.chdir(base_dir)

    def apply_solution_settings(self) -> None:
        """(Re)aplica ``tolerance`` e ``max_iterations`` ao motor.

        Precisa ser chamada depois de **toda** compilação, e não uma vez no
        construtor: o ``Compile`` do OpenDSS repõe os dois nos padrões dele —
        medido, ``tolerance`` volta a 1e-4 e ``max_iterations`` a 15. Um wrapper
        que recompilasse o circuito perderia o ajuste sem nada avisando, e a
        próxima solução seria resolvida com uma precisão que ninguém pediu.

        Os valores pedidos ficam guardados na instância justamente para
        sobreviver a essas reposições. ``None`` significa "não mexer", de modo
        que quem não pede nada continua com o padrão do motor.
        """
        if self._tolerance is not None:
            self.dss.solution.tolerance = self._tolerance
        if self._max_iterations is not None:
            self.dss.solution.max_iterations = self._max_iterations

    def invalidate_snapshot(self) -> None:
        """Drop cached solution results.

        Called on every solve and on every circuit edit. Any code that mutates
        the circuit outside this wrapper must call it, or reads will keep
        serving values from the superseded solution.
        """
        self._snapshot.clear()

    def run_command(self, cmd: str) -> None:
        """
        Executes a direct text command in the OpenDSS engine.

        Args:
            cmd (str): The DSS command to execute.

        Raises:
            OpenDSSException: If the command returns an error and fail_on_error is True.
        """
        self.invalidate_snapshot()
        status = self.dss.text(cmd)
        if status and "error" in status.lower() and self.fail_on_error:
            self.fail(f"Status ({cmd}): {status}")
        if status:
            self.print(f"Status ({cmd}): {status}")

    def redirect(self, filename: str) -> None:
        """
        Compiles a specific .dss file.

        Args:
            filename (str): Path to the file.
        """
        self.print(f"Running file: {filename}")
        self.invalidate_snapshot()
        self.dss.text(f'compile "{filename}"')
        # O compile repoe os ajustes de solucao; ver apply_solution_settings.
        self.apply_solution_settings()

    def run_dss(self, no_controls: bool = False) -> None:
        """Resolve o fluxo de potência e confere se a solução convergiu.

        Um solve que para no limite de iterações devolve tensões com a mesma
        cara das de um solve convergido, e o motor não reclama: ``converged``
        precisa ser consultado. Sem isso um passo truncado segue adiante como se
        estivesse certo, e num estudo de vários dias nada no resultado denuncia.

        A falha respeita ``fail_on_error``: por padrão interrompe, e com o erro
        desligado apenas registra. Quem precisa tolerar um passo ruim — em vez
        de perder a execução inteira — desliga o erro e acompanha o estado pelo
        modelo mosaik ``Circuit``, que expõe ``converged`` e ``iterations``.

        Args:
            no_controls: Se ``True``, usa ``solve_no_control()``.

        Raises:
            OpenDSSException: Se a solução não convergir e ``fail_on_error``
                estiver ligado.
        """
        self.invalidate_snapshot()
        try:
            if no_controls:
                self.dss.solution.solve_no_control()
            else:
                self.dss.solution.solve()

            # Manually update storage state after solution
            if self.includes_elements.get("Storage", False):
                self.dss.text("UpdateStorage")

        except Exception as e:
            self.dss.text("export Eventlog")
            self.fail(f"An error occurred during DSS solution: {e}")
            return

        if not self.dss.solution.converged:
            self.fail(
                f"A solucao nao convergiu em {self.dss.solution.iterations} iteracoes "
                f"(max_iterations={self.dss.solution.max_iterations}, "
                f"tolerance={self.dss.solution.tolerance:g}). As tensoes resultantes "
                "nao resolvem o circuito; aumente max_iterations ao construir o "
                "wrapper, ou desligue fail_on_error e acompanhe `converged` pelo "
                "modelo Circuit."
            )

    def set_element(self, name: str, element: str) -> None:
        """
        Sets the active element in the DSS circuit.

        Args:
            name (str): Element name (e.g., 'load1').
            element (str): Element class (e.g., 'Load').
        """
        full_name = f"{element}.{name}"
        self.dss.circuit.set_active_element(full_name)
        if self.dss.cktelement.name.lower() != full_name.lower():
            raise OpenDSSException(f'{element} "{name}" does not exist')

    def print(self, *msg: Any) -> None:
        """Prints a message with timestamp and class name."""
        print(f"{dt.datetime.now()} - {self.name}:", *msg)

    def fail(self, *msg: Any) -> None:
        """Raises an exception or prints an error depending on fail_on_error configuration."""
        if self.fail_on_error:
            raise OpenDSSException(*msg)
        else:
            self.print(*msg)
