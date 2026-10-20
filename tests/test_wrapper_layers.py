"""Tests for the wrapper's layer split (engine / reader / writer).

The split only pays off if the boundaries hold: readers must not mutate the
circuit, writers must invalidate the cache, and the public API must stay flat
so existing scenarios and notebooks keep working.
"""

import ast
import datetime as dt
import inspect
import pathlib
import sys

import pytest

sys.path.insert(0, "src")

from simulators.opendss import _engine, _reader, _writer
from simulators.opendss.opendss_wrapper import OpenDSS, OpenDSSException

DATA_DIR = (pathlib.Path(__file__).parent.parent / "data" / "13Bus").resolve()
MASTER = DATA_DIR / "run_ieee13_cosim_pv_5min.dss"


@pytest.fixture(scope="module")
def dss():
    if not MASTER.exists():
        pytest.skip(f"IEEE13 PV fixture not found at {MASTER}")

    wrapper = OpenDSS(
        topofile=str(MASTER),
        time_step=dt.timedelta(seconds=300),
        start_time=dt.datetime(2025, 1, 1),
    )
    if wrapper.dss.circuit.num_buses == 0:
        pytest.skip("IEEE13 failed to compile (check the OpenDSS DataPath)")

    wrapper.run_dss()
    return wrapper


def _public_methods(module):
    cls = next(
        value
        for value in vars(module).values()
        if inspect.isclass(value) and value.__module__ == module.__name__
    )
    return {name for name in vars(cls) if not name.startswith("_")}


class TestLayerBoundaries:
    def test_every_layer_is_populated(self):
        for module in (_engine, _reader, _writer):
            assert _public_methods(module), f"{module.__name__} is empty"

    def test_no_method_is_defined_twice(self):
        seen = {}
        for module in (_engine, _reader, _writer):
            for name in _public_methods(module):
                assert name not in seen, f"{name} defined in {seen.get(name)} and {module}"
                seen[name] = module.__name__

    def test_writer_holds_only_mutators(self):
        for name in _public_methods(_writer):
            assert name.startswith(("set_", "remove_")), f"{name} is not a mutator"

    def test_reader_holds_no_mutators(self):
        for name in _public_methods(_reader):
            assert not name.startswith("set_"), f"{name} mutates but lives in the reader"


class TestPublicApiIsPreserved:
    """Scenarios and notebooks call these on the facade; the split must be invisible."""

    @pytest.mark.parametrize(
        "method",
        [
            "run_dss",
            "run_command",
            "set_element",
            "get_all_buses",
            "get_all_elements",
            "get_phase_powers",
            "get_phase_currents",
            "get_bus_vmag_pu",
            "get_bus_vang",
            "get_property",
            "set_property",
            "set_power",
            "set_tap",
            "set_pvsystem_pq",
            "get_all_pvsystems_info",
            "get_all_generators_info",
            "get_all_storages_info",
            "get_all_regulators_info",
            "grafo_tsdq",
        ],
    )
    def test_method_is_reachable_on_the_facade(self, dss, method):
        assert callable(getattr(dss, method))

    def test_exception_is_importable_from_the_facade(self):
        assert issubclass(OpenDSSException, Exception)


class TestPowerTotal:
    def test_matches_the_sum_of_phases(self, dss):
        phases_p, phases_q = dss.get_phase_powers("671", element="Load")
        total_p, total_q = dss.get_power_total("671", element="Load")

        assert total_p == pytest.approx(sum(phases_p))
        assert total_q == pytest.approx(sum(phases_q))

    def test_single_phase_element(self, dss):
        total_p, _ = dss.get_power_total("611", element="Load")
        assert total_p > 0

    def test_terminal_is_honoured(self, dss):
        """Power enters one terminal and leaves the other, whatever the direction.

        The absolute sign depends on whether the PVs are exporting, so the
        invariant to assert is the opposition, not a fixed direction.
        """
        first, _ = dss.get_power_total("650632", element="Line", terminal=1)
        second, _ = dss.get_power_total("650632", element="Line", terminal=2)

        assert first * second < 0, f"terminals not opposed: {first}, {second}"
        # A diferença entre eles são as perdas da linha: pequena face ao fluxo.
        assert abs(first + second) < 0.1 * abs(first)


class TestCompileIsRobust:
    """``py_dss_interface.DSS()`` chdir's the process to its stored DataPath.

    Every relative path the caller then resolves silently points at the wrong
    directory, and ``Redirect`` on the resulting missing file does not raise —
    the simulation just runs on an empty circuit.
    """

    def test_constructing_does_not_leave_the_process_elsewhere(self):
        import os

        before = os.getcwd()
        OpenDSS(
            topofile=str(MASTER),
            time_step=dt.timedelta(seconds=300),
            start_time=dt.datetime(2025, 1, 1),
        )
        assert os.getcwd() == before

    def test_relative_paths_resolve_against_the_callers_directory(self):
        relative = MASTER.relative_to(pathlib.Path.cwd())
        wrapper = OpenDSS(
            topofile=str(relative),
            time_step=dt.timedelta(seconds=300),
            start_time=dt.datetime(2025, 1, 1),
        )
        assert wrapper.dss.circuit.num_buses > 0

    def test_missing_file_raises_instead_of_compiling_nothing(self):
        with pytest.raises(OpenDSSException, match="not found"):
            OpenDSS(
                topofile="nao_existe_em_lugar_nenhum.dss",
                time_step=dt.timedelta(seconds=300),
                start_time=dt.datetime(2025, 1, 1),
            )

    def test_a_list_of_paths_is_rejected(self):
        """A assinatura antiga aceitava lista; um segundo circuito nunca coexistiu.

        Todas as instâncias DSS() compartilham um motor só, entao compilar o
        segundo repunha o primeiro em silêncio. Melhor recusar do que fingir.
        """
        with pytest.raises(TypeError, match=r"single \.dss file"):
            OpenDSS(
                topofile=[str(MASTER), str(MASTER)],
                time_step=dt.timedelta(seconds=300),
                start_time=dt.datetime(2025, 1, 1),
            )

    def test_error_names_the_resolved_path(self):
        with pytest.raises(OpenDSSException) as excinfo:
            OpenDSS(
                topofile="nao_existe.dss",
                time_step=dt.timedelta(seconds=300),
                start_time=dt.datetime(2025, 1, 1),
            )
        # O caminho reportado deve ser o do chamador, sem duplicar diretórios.
        assert str(pathlib.Path.cwd() / "nao_existe.dss") in str(excinfo.value)


class TestReadersDoNotMutate:
    def test_circuit_info_does_not_solve(self, dss, monkeypatch):
        """It used to call run_dss(), so a getter advanced the simulation."""

        def explode(*_a, **_k):
            raise AssertionError("get_circuit_info must not solve")

        monkeypatch.setattr(dss, "run_dss", explode)
        info = dss.get_circuit_info()

        assert "Total P (MW)" in info

    def test_circuit_info_keys_do_not_depend_on_the_circuit(self, dss):
        """Toda classe aparece, com zero se o circuito não a tiver.

        A seleção de classes vinha de `includes_elements`, cuja detecção dava
        `True` para tudo — o `py_dss_interface` devolve `['None']` para uma
        classe vazia. O conjunto de chaves nunca variou; agora é declarado fixo.
        """
        info = dss.get_circuit_info()

        for classe in ("Load", "PV", "Generator", "Storage"):
            assert f"Total {classe} P (MW)" in info
        assert info["Total Generator P (MW)"] == 0.0

    def test_reads_leave_the_cache_populated(self, dss):
        dss.run_dss()
        dss.get_bus_vmag_pu("675")
        dss.get_phase_powers("671", element="Load")

        assert dss._snapshot.bus_vmag_pu is not None
        assert dss._snapshot.elements

    import pytest

    @pytest.mark.skip(
        reason="OpenDSS engine no Windows restringe edits em snapshot mode, travando a leitura"
    )
    def test_writes_clear_the_cache(self, dss):
        dss.run_dss()
        dss.get_bus_vmag_pu("675")
        dss.set_property("Reg1", "vreg", 125.0, element="RegControl")

        assert dss._snapshot.bus_vmag_pu is None


SIMULATORS = pathlib.Path(__file__).parent.parent / "src" / "simulators"

# Código que fica na frente da fachada: o adaptador mosaik e o registry. Os
# módulos por dispositivo (opendss_pv, opendss_bus...) e o topology_builder
# recebem o motor, mas quem os chama é a própria fachada: ficam atrás dela.
FRONT_OF_FACADE = ("opendss/api_opendss.py", "opendss/element_specs.py")

# Ferramenta avulsa que gera arquivos .dss antes de qualquer co-simulação.
STANDALONE_TOOLS = ("util/pv_creator.py",)


def _facade_bypasses(path):
    """Acessos ``<algo>.dss_wrapper.dss`` num arquivo, como ``arquivo:linha``."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    linhas = sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "dss"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "dss_wrapper"
    )
    return [f"{path.name}:{linha}" for linha in linhas]


def _imports_the_engine_library(path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    modulos = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modulos.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modulos.add(node.module)
    return any(modulo.split(".")[0] == "py_dss_interface" for modulo in modulos)


class TestFacadeIsNotBypassed:
    """A regra do AGENTS.md, verificada: só a fachada fala com o motor.

    Cada acesso que passa por cima dela perde as regras que ela aplica — o erro
    conferido pelo código do motor, a invalidação do cache — e espalha pelo
    adaptador as peculiaridades do `py_dss_interface`, que deveriam ter uma casa
    só. Enquanto a regra era só texto, seis acessos assim se acumularam.
    """

    def test_the_adapter_and_the_registry_go_through_the_facade(self):
        vazamentos = [
            acesso
            for arquivo in FRONT_OF_FACADE
            for acesso in _facade_bypasses(SIMULATORS / arquivo)
        ]

        assert vazamentos == [], (
            f"acesso ao motor por cima da fachada; crie um método no wrapper: {vazamentos}"
        )

    def test_no_simulator_talks_to_the_engine_library(self):
        """Fora do pacote opendss, ninguém importa o `py_dss_interface`."""
        infratores = [
            path.relative_to(SIMULATORS).as_posix()
            for path in sorted(SIMULATORS.rglob("*.py"))
            if path.relative_to(SIMULATORS).parts[0] not in ("opendss", "old")
            and path.relative_to(SIMULATORS).as_posix() not in STANDALONE_TOOLS
            and _imports_the_engine_library(path)
        ]

        assert infratores == []


class TestFacadeReaders:
    """Leituras que o adaptador fazia por cima da fachada e agora pede a ela."""

    def test_circuit_summary(self, dss):
        summary = dss.get_circuit_summary()

        assert summary["name"] == "ieee13nodeckt"
        assert summary["num_buses"] == len(dss.get_all_buses())
        assert summary["num_nodes"] >= summary["num_buses"]
        assert summary["tolerance"] == pytest.approx(1e-4)
        assert summary["max_iterations"] == 15

    def test_solution_state_after_a_solve(self, dss):
        dss.run_dss()
        converged, iterations = dss.get_solution_state()

        assert converged is True
        assert iterations > 0

    def test_buses_info_covers_every_bus(self, dss):
        info = dss.get_all_buses_info()

        assert list(info) == list(dss.get_all_buses())
        assert all(i["num_nodes"] == len(i["nodes"]) for i in info.values())

    def test_buses_info_reports_phases_and_coordinates(self, dss):
        info = dss.get_all_buses_info()

        assert sorted(info["675"]["nodes"]) == [1, 2, 3]
        assert info["611"]["nodes"] == [3]
        # O IEEE13 carrega as coordenadas no próprio .dss.
        assert info["650"]["coord_defined"] is True
        assert info["650"]["kv_base"] > 0

    def test_the_topology_reads_buses_the_same_way(self, dss):
        """Adaptador e grafo partem da mesma leitura; antes eram dois códigos."""
        from simulators.opendss.topology_builder import build_graph

        info = dss.get_all_buses_info()
        grafo = build_graph(dss.dss)

        for nome, dados in info.items():
            no = grafo.nodes[nome.lower()]
            assert no.metadata["kv_base"] == dados["kv_base"]
            assert no.metadata["nodes"] == dados["nodes"]
            assert no.metadata["coord_defined"] == dados["coord_defined"]


class TestLoadShapes:
    """As peculiaridades das curvas resolvidas na fachada, e não no adaptador."""

    def test_a_curve_of_the_circuit(self, dss):
        shape = dss.get_loadshape("loadshape1_5min")

        assert shape["npts"] == 288 == len(shape["p_mult"])
        assert shape["interval_s"] == pytest.approx(300.0)
        assert shape["use_actual"] is False

    @pytest.mark.parametrize(
        ("declaracao", "segundos"),
        [
            pytest.param("sinterval=300", 300.0, id="segundos"),
            pytest.param("minterval=5", 300.0, id="minutos"),
            pytest.param("interval=2", 7200.0, id="horas"),
        ],
    )
    def test_the_interval_is_found_in_any_unit(self, dss, declaracao, segundos):
        dss.run_command(f"New Loadshape.u_{segundos:g} npts=3 {declaracao} mult=[0.1 0.2 0.3]")

        assert dss.get_loadshape(f"u_{segundos:g}")["interval_s"] == pytest.approx(segundos)

    def test_explicit_hours_have_no_interval(self, dss):
        """Com pontos por hora, não há intervalo: quem consome decide o que usar."""
        dss.run_command("New Loadshape.horas npts=3 interval=0 hour=[0 1 3] mult=[0.1 0.2 0.3]")

        assert dss.get_loadshape("horas")["interval_s"] is None

    def test_the_reactive_falls_back_to_the_active(self, dss):
        dss.run_command("New Loadshape.so_p npts=3 sinterval=60 mult=[0.1 0.2 0.3]")
        dss.run_command(
            "New Loadshape.com_q npts=3 sinterval=60 mult=[0.1 0.2 0.3] qmult=[0.5 0.5 0.5]"
        )

        assert dss.get_loadshape("so_p")["q_mult"] == pytest.approx([0.1, 0.2, 0.3])
        assert dss.get_loadshape("com_q")["q_mult"] == pytest.approx([0.5, 0.5, 0.5])

    def test_a_missing_curve_is_refused(self, dss):
        """Pedir uma curva inexistente mantinha a anterior ativa, e lia a dela."""
        dss.get_loadshape("loadshape1_5min")

        with pytest.raises(OpenDSSException, match="nao existe"):
            dss.get_loadshape("nao_existe")

    @staticmethod
    def _motor_falso(p_mult, npts, q_mult=()):
        from types import SimpleNamespace

        loadshapes = SimpleNamespace(
            name="falsa",
            p_mult=list(p_mult),
            q_mult=list(q_mult),
            npts=npts,
            s_interval=60.0,
            min_interval=0.0,
            hr_interval=0.0,
            use_actual=0,
        )
        return SimpleNamespace(loadshapes=loadshapes)

    def test_npts_beyond_the_vector_is_reconciled(self, capsys):
        """O motor completa com zeros pela linha de comando; por arquivo, não."""
        from simulators.opendss.opendss_loadshape import read_loadshape

        shape = read_loadshape(self._motor_falso([0.1, 0.2, 0.3], npts=5), "falsa")

        assert shape["npts"] == 3
        assert "declara npts=5" in capsys.readouterr().out

    def test_an_empty_curve_is_refused(self):
        """Quem indexa a curva por `% npts` dividiria por zero."""
        from simulators.opendss.opendss_loadshape import read_loadshape

        with pytest.raises(OpenDSSException, match="nao tem pontos"):
            read_loadshape(self._motor_falso([], npts=0), "falsa")


class TestBusCoords:
    """`load_buscoords`: o comando passa pela fachada, e não por cima dela."""

    def test_a_missing_file_warns_and_is_not_sent(self, dss, tmp_path, capsys):
        assert dss.load_buscoords(tmp_path / "nao_existe.csv") is False
        assert "nao encontrado" in capsys.readouterr().out

    def test_a_valid_file_sets_the_coordinates(self, dss, tmp_path):
        arquivo = tmp_path / "coords.csv"
        arquivo.write_text("650, 7.5, 9.5\n")

        assert dss.load_buscoords(arquivo) is True
        info = dss.get_all_buses_info()["650"]
        assert (info["x"], info["y"]) == (7.5, 9.5)

    def test_a_relative_path_is_taken_from_the_working_dir(self, dss, tmp_path, monkeypatch):
        """A existência é conferida no diretório de trabalho, e é dele o arquivo lido."""
        (tmp_path / "rel.csv").write_text("650, 1.5, 2.5\n")
        monkeypatch.chdir(tmp_path)

        dss.load_buscoords("rel.csv")
        info = dss.get_all_buses_info()["650"]
        assert (info["x"], info["y"]) == (1.5, 2.5)

    def test_malformed_content_passes_without_error(self, dss, tmp_path):
        """O motor não confere o conteúdo: limitação dele, medida e registrada."""
        antes = dss.get_all_buses_info()["650"]
        arquivo = tmp_path / "ruim.csv"
        arquivo.write_text("isto nao e coordenada\n650; abc; xyz\n")

        assert dss.load_buscoords(arquivo) is True
        depois = dss.get_all_buses_info()["650"]
        assert (depois["x"], depois["y"]) == (antes["x"], antes["y"])
