"""Tests for the CSV collector.

O arquivo que este simulador escreve é o resultado do estudo, e o modo de falhar
que importa não é o crash: é o CSV bem formado com os valores nas colunas
erradas, que ninguém percebe ao abrir. Estes testes fixam o alinhamento.

Não usam OpenDSS: o coletor só recebe dicionários.
"""

import csv
import pathlib
import sys

import pytest

sys.path.insert(0, "src")

from simulators.collector.collector import Collector, SchemaError

START = "2025-01-01 00:00:00"


@pytest.fixture
def coletor(tmp_path):
    """Um coletor pronto para receber passos, gravando em arquivo temporário."""
    saida = tmp_path / "resultado.csv"
    sim = Collector()
    sim.init("Collector-0", 1.0, start_date=START, output_file=str(saida))
    sim.create(1, "Monitor")
    sim.output_path = saida
    return sim


def entrada(**atributos):
    """Monta o `inputs` do mosaik: {eid: {attr: {src: valor}}}."""
    return {"Monitor": {attr: fontes for attr, fontes in atributos.items()}}


def ler(caminho):
    with open(caminho, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class TestHappyPath:
    def test_writes_header_and_row(self, coletor):
        coletor.step(0, entrada(V1_pu={"DSS-0.Bus-1": 1.02}), 0)
        coletor.finalize()

        linhas = ler(coletor.output_path)
        assert len(linhas) == 1
        assert linhas[0]["DSS-0.Bus-1-V1_pu"] == "1.02"
        assert linhas[0]["date"] == "2025-01-01 00:00:00"

    def test_the_date_follows_the_step(self, coletor):
        coletor.step(0, entrada(V1_pu={"DSS-0.Bus-1": 1.0}), 0)
        coletor.step(900, entrada(V1_pu={"DSS-0.Bus-1": 1.0}), 0)
        coletor.finalize()

        datas = [linha["date"] for linha in ler(coletor.output_path)]
        assert datas == ["2025-01-01 00:00:00", "2025-01-01 00:15:00"]

    def test_several_sources_and_attributes(self, coletor):
        coletor.step(
            0,
            entrada(
                V1_pu={"DSS-0.Bus-1": 1.01, "DSS-0.Bus-2": 0.99},
                P1_w={"DSS-0.Line-a": 250.0},
            ),
            0,
        )
        coletor.finalize()

        linha = ler(coletor.output_path)[0]
        assert linha["DSS-0.Bus-1-V1_pu"] == "1.01"
        assert linha["DSS-0.Bus-2-V1_pu"] == "0.99"
        assert linha["DSS-0.Line-a-P1_w"] == "250.0"


class TestAlignment:
    """O defeito que motivou a reescrita: valores na coluna do vizinho."""

    def test_a_missing_attribute_leaves_its_cell_empty(self, coletor):
        """Não desloca os demais — o coletor é event-based, faltar é legítimo."""
        coletor.step(0, entrada(V={"a": 1.0}, P={"b": 2.0}, Q={"c": 3.0}), 0)
        coletor.step(1, entrada(V={"a": 1.1}, Q={"c": 3.3}), 0)
        coletor.finalize()

        segunda = ler(coletor.output_path)[1]
        assert segunda["a-V"] == "1.1"
        assert segunda["b-P"] == ""
        assert segunda["c-Q"] == "3.3"

    def test_a_different_key_order_does_not_shift_values(self, coletor):
        """A ordem do `inputs` não é contrato; o nome da coluna é."""
        coletor.step(0, entrada(V={"a": 1.0}, P={"b": 2.0}), 0)
        coletor.step(1, entrada(P={"b": 2.2}, V={"a": 1.1}), 0)
        coletor.finalize()

        segunda = ler(coletor.output_path)[1]
        assert segunda["a-V"] == "1.1"
        assert segunda["b-P"] == "2.2"

    def test_a_new_column_raises(self, coletor):
        """Essa não tem onde ser gravada; gravá-la em silêncio é o defeito."""
        coletor.step(0, entrada(V={"a": 1.0}), 0)

        with pytest.raises(SchemaError, match="b-P"):
            coletor.step(1, entrada(V={"a": 1.1}, P={"b": 2.0}), 0)

    def test_the_error_says_what_to_do(self, coletor):
        coletor.step(0, entrada(V={"a": 1.0}), 0)

        with pytest.raises(SchemaError) as erro:
            coletor.step(1, entrada(V={"a": 1.1}, P={"b": 2.0}), 0)

        assert "cabecalho" in str(erro.value)
        assert str(coletor.output_path) in str(erro.value)

    def test_every_row_has_the_width_of_the_header(self, coletor):
        coletor.step(0, entrada(V={"a": 1.0}, P={"b": 2.0}), 0)
        coletor.step(1, entrada(V={"a": 1.1}), 0)
        coletor.step(2, entrada(P={"b": 2.2}), 0)
        coletor.finalize()

        with open(coletor.output_path, newline="", encoding="utf-8") as f:
            larguras = {len(linha) for linha in csv.reader(f)}

        assert len(larguras) == 1, f"linhas de larguras diferentes: {larguras}"


class TestFirstWrite:
    """O cabeçalho sai na primeira escrita, não no passo de tempo zero."""

    def test_a_first_event_after_time_zero_still_writes_the_header(self, coletor):
        coletor.step(1800, entrada(V={"a": 1.0}), 0)
        coletor.finalize()

        linhas = ler(coletor.output_path)
        assert linhas[0]["a-V"] == "1.0"

    def test_it_truncates_a_previous_run(self, coletor):
        """Sem isso, o resultado se somava ao da execução anterior."""
        coletor.output_path.write_text("lixo de uma execucao antiga\n" * 5, encoding="utf-8")

        coletor.step(300, entrada(V={"a": 1.0}), 0)
        coletor.finalize()

        conteudo = coletor.output_path.read_text(encoding="utf-8")
        assert "lixo" not in conteudo
        assert len(ler(coletor.output_path)) == 1

    def test_a_step_with_no_inputs_does_not_crash(self, coletor):
        """Antes levantava ValueError ao montar um DataFrame só de escalares."""
        coletor.step(0, {}, 0)
        coletor.step(1, entrada(V={"a": 1.0}), 0)
        coletor.finalize()

        assert ler(coletor.output_path)[0]["a-V"] == "1.0"

    def test_an_empty_step_after_the_header_writes_an_empty_row(self, coletor):
        coletor.step(0, entrada(V={"a": 1.0}), 0)
        coletor.step(1, {}, 0)
        coletor.finalize()

        linhas = ler(coletor.output_path)
        assert len(linhas) == 2
        assert linhas[1]["a-V"] == ""

    def test_no_file_is_created_before_the_first_value(self, coletor):
        """Um passo vazio não pode congelar um cabeçalho vazio."""
        coletor.step(0, {}, 0)

        assert not coletor.output_path.exists()


class TestMemory:
    def test_nothing_is_accumulated_by_default(self, coletor):
        for t in range(50):
            coletor.step(t, entrada(V={"a": float(t)}), 0)
        coletor.finalize()

        assert coletor.data == {}

    def test_print_results_still_works(self, tmp_path, capsys):
        sim = Collector()
        sim.init(
            "Collector-0",
            1.0,
            start_date=START,
            output_file=str(tmp_path / "r.csv"),
            print_results=True,
        )
        sim.create(1, "Monitor")
        sim.step(0, entrada(V={"a": 1.0}), 0)
        sim.finalize()

        assert "a" in capsys.readouterr().out


class TestIncrementalWrite:
    def test_rows_are_readable_before_finalize(self, coletor):
        """Uma execução interrompida não pode perder o que já mediu."""
        coletor.step(0, entrada(V={"a": 1.0}), 0)
        coletor.step(1, entrada(V={"a": 2.0}), 0)

        assert len(ler(coletor.output_path)) == 2

    def test_finalize_closes_the_file(self, coletor):
        coletor.step(0, entrada(V={"a": 1.0}), 0)
        coletor.finalize()

        assert coletor._file is None

    def test_the_default_output_stays_out_of_the_source_tree(self):
        """O padrão apontava para dentro de src/simulators/."""
        import inspect

        padrao = inspect.signature(Collector.init).parameters["output_file"].default
        partes = pathlib.Path(padrao).parts

        assert "src" not in partes
        assert partes[-2:] == ("output", "results.csv")
