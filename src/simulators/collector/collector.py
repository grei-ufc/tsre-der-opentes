"""Coletor de dados: grava num CSV tudo o que os simuladores lhe enviam.

O arquivo que este módulo escreve **é** o resultado do estudo. Por isso as três
decisões abaixo, todas sobre o mesmo risco: um CSV bem formado com os valores
nas colunas erradas não se distingue de um correto ao abrir.

1. **As colunas são fixadas na primeira escrita** e cada linha seguinte é
   gravada *por nome*. Antes, o cabeçalho saía da ordem de iteração do
   ``inputs`` e as linhas seguintes levavam só os valores, na ordem daquele
   passo: bastava a ordem mudar para os dados entrarem trocados, sem erro.
2. **Uma coluna nova depois do cabeçalho interrompe.** Essa não tem onde ser
   gravada, e gravá-la em silêncio é o defeito. Já um atributo que *falta* num
   passo é legítimo — o coletor é ``event-based`` e declara ``any_inputs``, e
   nem toda fonte dispara a cada passo —, então sai como célula vazia.
3. **A escrita é incremental**, com um ``csv.writer`` sobre um arquivo aberto
   uma vez e ``flush`` por linha. O acúmulo em memória só acontece quando
   ``print_results`` está ligado.
"""

import collections
import csv
from pathlib import Path

import mosaik_api_v3
import pandas as pd

current_dir = Path(__file__).resolve().parent
project_dir = current_dir.parent.parent.parent

META = {
    "api_version": "3.0",
    "type": "event-based",
    "models": {
        "Monitor": {
            "public": True,
            "any_inputs": True,
            "params": [],
            "attrs": [],
        },
    },
}


class SchemaError(Exception):
    """Um atributo novo apareceu depois de o cabeçalho ter sido fixado."""


class Collector(mosaik_api_v3.Simulator):
    def __init__(self):
        super().__init__(META)
        self.eid = None
        self.print_results = False
        # Só alimentado quando print_results está ligado: guardar tudo custa
        # O(fontes x atributos x passos) e o CSV já é escrito de qualquer forma.
        self.data = collections.defaultdict(lambda: collections.defaultdict(dict))
        self._columns = None
        self._file = None
        self._writer = None

    def init(
        self,
        sid,
        time_resolution,
        start_date,
        date_format="%Y-%m-%d %H:%M:%S",
        output_file=project_dir / "output" / "results.csv",
        print_results=False,
    ):
        self.time_resolution = time_resolution
        self.start_date = pd.to_datetime(start_date, format=date_format)
        self.output_file = output_file
        self.print_results = print_results
        return self.meta

    def create(self, num, model):
        if num > 1 or self.eid is not None:
            raise RuntimeError("Can only create one instance of Monitor.")

        self.eid = "Monitor"

        return [{"eid": self.eid, "type": model}]

    def step(self, time, inputs, max_advance):
        current_date = self.start_date + pd.Timedelta(time * self.time_resolution, unit="seconds")

        linha = {}
        for attr, values in inputs.get(self.eid, {}).items():
            for src, value in values.items():
                linha[f"{src}-{attr}"] = value
                if self.print_results:
                    self.data[src][attr][time] = value

        if self._writer is None:
            # Nada a gravar e nenhum esquema a fixar: um passo vazio antes da
            # primeira entrada não pode congelar um cabeçalho vazio, que faria
            # toda coluna posterior parecer nova.
            if not linha:
                return None
            self._open(sorted(linha))

        novas = [coluna for coluna in linha if coluna not in self._columns]
        if novas:
            raise SchemaError(
                f"Atributos que nao estavam no cabecalho apareceram no passo {time}: "
                f"{sorted(novas)}. O cabecalho de '{self.output_file}' foi fixado na "
                "primeira escrita e nao pode receber colunas novas; grava-los agora "
                "desalinharia o arquivo inteiro. Conecte todas as fontes antes do "
                "primeiro passo, ou grave num arquivo por conjunto de atributos."
            )

        self._writer.writerow(
            [current_date.strftime("%Y-%m-%d %H:%M:%S")]
            + [linha.get(coluna, "") for coluna in self._columns]
        )
        # Um estudo de dias não pode perder o que já mediu se for interrompido.
        self._file.flush()

        return None

    def _open(self, columns):
        """Abre o arquivo e fixa as colunas, na primeira vez que houver o que gravar.

        Fixar aqui, e não no passo ``time == 0``, é o que faz o cabeçalho
        aparecer mesmo quando a primeira entrada chega depois — num coletor
        ``event-based`` a primeira pode chegar a qualquer momento. Antes, nesse
        caso, o arquivo era aberto em modo de anexação e o resultado se somava
        ao da execução anterior.
        """
        Path(self.output_file).parent.mkdir(parents=True, exist_ok=True)
        self._columns = list(columns)
        # O handle tem de sobreviver a esta função: fica aberto entre os passos
        # e é fechado no `finalize`. Um gerenciador de contexto aqui reabriria o
        # arquivo a cada linha — que é justamente o que a versão anterior fazia.
        self._file = open(self.output_file, "w", newline="", encoding="utf-8")  # noqa: SIM115
        self._writer = csv.writer(self._file)
        self._writer.writerow(["date", *self._columns])

    def finalize(self):
        if self._file is not None:
            self._file.close()
            self._file = None
            self._writer = None

        if self.print_results:
            for sim, sim_data in sorted(self.data.items()):
                print(f"- {sim}:")
                for attr, values in sorted(sim_data.items()):
                    print(f"  - {attr}: {values}")


if __name__ == "__main__":
    mosaik_api_v3.start_simulation(Collector())
