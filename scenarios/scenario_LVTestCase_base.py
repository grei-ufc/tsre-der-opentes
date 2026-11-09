"""Cenário Base (0% PV) para a rede IEEE European LV Test Feeder (LVTestCase).

Executa a co-simulação via Mosaik + OpenDSS para a rede em baixa tensão sem geradores
fotovoltaicos (0% de penetração), simulando 24 horas (288 passos de 5 minutos).
Monitora as tensões em todas as barras e os fluxos de potência/corrente na linha LINE1.
"""

import sys
from pathlib import Path

import mosaik
from mosaik.util import connect_many_to_one

# ==============================================================================
# 1. CAMINHOS LOCAIS
# ==============================================================================
CURRENT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

DATA_DIR = PROJECT_ROOT / "data" / "LVTestCase"
CIRCUITO_DSS = DATA_DIR / "run_LVTestCase_base.dss"

OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
ARQUIVO_RESULTADOS_CSV = OUTPUT_DIR / "result_LVTestCase_base.csv"

START_DATE = "2026-01-01 00:00:00"
STEP_SIZE = 60 * 5  # 5 minutos (300 segundos)
N_PASSOS = 288  # 24 horas
END_TIME = N_PASSOS * STEP_SIZE

# ==============================================================================
# 2. CONFIGURAÇÃO DOS SIMULADORES
# ==============================================================================
SIM_CONFIG = {
    "DSS": {
        "python": "simulators.opendss.api_opendss:OpenDSSSimulator",
    },
    "Collector": {
        "python": "simulators.collector.collector:Collector",
    },
}


def run_scenario(output_csv: Path | str | None = None, dss_file: Path | str | None = None):
    """Executa a co-simulação Mosaik do caso base (0% PV) da rede LVTestCase."""
    target_dss = Path(dss_file) if dss_file is not None else CIRCUITO_DSS
    out_csv = Path(output_csv) if output_csv is not None else ARQUIVO_RESULTADOS_CSV
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    if not target_dss.exists():
        print(f"[ERRO]: Arquivo DSS não encontrado em:\n{target_dss}")
        return None

    with mosaik.World(SIM_CONFIG) as world:
        print("--- Inicializando Simuladores: Caso Base (0% PV) ---")
        dss_sim = world.start(
            "DSS",
            topofile=str(target_dss),
            step_size=STEP_SIZE,
            fail_on_error=False,
            max_iterations=150,
        )

        collector = world.start(
            "Collector",
            start_date=START_DATE,
            output_file=str(out_csv),
            print_results=False,
        )

        print("Instanciando a Grid do OpenDSS...")
        grid = dss_sim.Grid()
        monitor = collector.Monitor()

        # Monitoramento das tensões de todas as barras
        print("Conectando barras ao monitor...")
        todas_as_barras = [e for e in grid.children if e.type == "Bus"]
        connect_many_to_one(world, todas_as_barras, monitor, "V1_pu", "V2_pu", "V3_pu")

        # Monitoramento da linha do alimentador (LINE1)
        line_entities = [e for e in grid.children if e.eid.lower() == "line-line1"]
        if line_entities:
            world.connect(
                line_entities[0],
                monitor,
                "I1_A",
                "I1_ang",
                "I2_A",
                "I2_ang",
                "I3_A",
                "I3_ang",
                "P1_w",
                "Q1_var",
                "P2_w",
                "Q2_var",
                "P3_w",
                "Q3_var",
            )
            print("Monitorando Linha de cabeceira: Line-LINE1")

        print(f"Executando co-simulação de 24h ({N_PASSOS} passos de {STEP_SIZE}s)...")
        world.run(until=END_TIME, print_progress=False)
        print("Simulação concluída com sucesso.")

        if out_csv.exists():
            print(f"Resultados salvos em: {out_csv}")
        return out_csv


if __name__ == "__main__":
    run_scenario()
