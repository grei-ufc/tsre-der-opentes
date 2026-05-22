import mosaik
import sys
import pprint
import pandas as pd
from pathlib import Path

# ==============================================================================
# 1. CAMINHOS NO HOST (Windows)
# ==============================================================================
CURRENT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = CURRENT_DIR.parent
DATA_DIR_HOST = PROJECT_ROOT / "data" / "13Bus"
CIRCUITO_DSS_HOST = DATA_DIR_HOST / "run_ieee13_cosim_pv_5min.dss"
OUTPUT_DIR_HOST = PROJECT_ROOT / "output"
OUTPUT_DIR_HOST.mkdir(parents=True, exist_ok=True)
ARQUIVO_RESULTADOS_CSV_HOST = OUTPUT_DIR_HOST / 'result_run_ieee13_cosim_SEM_pv_5min.csv'

# ==============================================================================
# 2. CAMINHOS NO CONTAINER (Linux/Docker)
# ==============================================================================
CONTAINER_DATA = "/app/src/data/13Bus"
CIRCUITO_DSS_CONT = f"{CONTAINER_DATA}/run_ieee13_cosim_pv_5min.dss"
IRRADIANCE_CONT = f"{CONTAINER_DATA}/ieee13_shape_pv_5min.csv"
TEMPERATURE_CONT = f"{CONTAINER_DATA}/ieee13_temperature_5min.csv"
ARQUIVO_RESULTADOS_CSV_CONT = "/app/output/result_run_ieee13_cosim_SEM_pv_5min.csv"

START_DATE = "2026-01-01 00:00:00"
STEP_SIZE = 60 * 5
N_PASSOS = 288
END_TIME = N_PASSOS * STEP_SIZE

# ==============================================================================
# 3. CONFIGURAÇÃO DE CONEXÃO (DOCKER)
# ==============================================================================
SIM_CONFIG = {
    'DSS': {
        'connect': 'localhost:5671',
    },
    'Collector': {
        'connect': 'localhost:5673',
    },
}

def run_scenario():
    if not CIRCUITO_DSS_HOST.exists():
        print(f"[ERRO]: Arquivo DSS não encontrado no Windows em:\n{CIRCUITO_DSS_HOST}")
        return

    with mosaik.World(SIM_CONFIG) as world:
        print("--- Conectando aos Simuladores no Docker ---")

        # 1. Iniciando Simuladores via Rede
        dss_sim = world.start(
            'DSS', 
            topofile=CIRCUITO_DSS_CONT, 
            step_size=STEP_SIZE)

        collector = world.start(
            'Collector',
            start_date=START_DATE,
            output_file=ARQUIVO_RESULTADOS_CSV_CONT,
            print_results=False
        )

        print("Instanciando a Grid do OpenDSS...")
        grid = dss_sim.Grid()
        
        monitor = collector.Monitor()

        # Monitorar Barra 650, 680 e 611
        target_names = ['650', '680', '611']
        for target_name in target_names:
            target_eid = f'Bus-{target_name}'
            bus_entities = [e for e in grid.children if e.eid == target_eid]
            if bus_entities:
                world.connect(bus_entities[0], monitor, 'V1_pu', 'V2_pu', 'V3_pu')
                print(f"Monitorando Barra: {target_eid}")

        target_names = ['650632', '671680', '684611']
        for target_name in target_names:
            target_eid = f'Line-{target_name}'
            line_entities = [e for e in grid.children if e.eid.lower() == target_eid.lower()]
            if line_entities:
                world.connect(line_entities[0], monitor,
                              'I1_A', 'I1_ang', 'I2_A', 'I2_ang', 'I3_A', 'I3_ang',
                          'P1_w', 'Q1_var', 'P2_w', 'Q2_var', 'P3_w', 'Q3_var')
            print(f"Monitorando Linha: {target_eid}")

        print(f"\nInicializando simulação de {N_PASSOS} para (Step={STEP_SIZE}...)")

        world.run(until=END_TIME, print_progress=False)
        print("Simulação concluída.")

        # --- Check Rápido ---
        if ARQUIVO_RESULTADOS_CSV_HOST.exists():
            print(f"\nResultados salvos em: {ARQUIVO_RESULTADOS_CSV_HOST}")
            
if __name__ == '__main__':
    run_scenario()