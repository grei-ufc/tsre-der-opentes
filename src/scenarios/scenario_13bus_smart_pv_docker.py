import mosaik
import sys
import pprint
import pandas as pd
from pathlib import Path
from mosaik.util import connect_many_to_one
from simulators.topologia import exportar_topologia

# ==============================================================================
# 1. CAMINHOS NO HOST (Windows)
# ==============================================================================
CURRENT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = CURRENT_DIR.parent
DATA_DIR_HOST = PROJECT_ROOT / "data" / "13Bus"
CIRCUITO_DSS_HOST = DATA_DIR_HOST / "run_ieee13_cosim_pv_5min.dss"
OUTPUT_DIR_HOST = PROJECT_ROOT / "output"
OUTPUT_DIR_HOST.mkdir(parents=True, exist_ok=True)
ARQUIVO_RESULTADOS_CSV_HOST = OUTPUT_DIR_HOST / 'result_run_ieee13_cosim_pv_5min.csv'
JSON_SAIDA = str(PROJECT_ROOT.parent / 'output' / 'topologia_ieee13.json')

# ==============================================================================
# 2. CAMINHOS NO CONTAINER (Linux/Docker)
# ==============================================================================
CONTAINER_DATA = "/app/src/data/13Bus"
CIRCUITO_DSS_CONT = f"{CONTAINER_DATA}/run_ieee13_cosim_pv_5min.dss"
IRRADIANCE_CONT = f"{CONTAINER_DATA}/ieee13_shape_pv_5min.csv"
TEMPERATURE_CONT = f"{CONTAINER_DATA}/ieee13_temperature_5min.csv"
ARQUIVO_RESULTADOS_CSV_CONT = "/app/output/result_run_ieee13_cosim_pv_5min.csv"

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
    'PVSimulator': {
        'connect': 'localhost:5678'
    },
    'InverterSim': {
        'connect': 'localhost:5680' # Porta 5680 = inverter-smart
    },
    'CSV_Irr': {
        'connect': 'localhost:5675' # Porta 5675 = csv-data-1
    },
    'CSV_Temp': {
        'connect': 'localhost:5676' # Porta 5676 = csv-data-2
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
        
        pv_sim = world.start(
            'PVSimulator',
            step_size=STEP_SIZE)
        
        inv_sim = world.start(
            'InverterSim',
            step_size=STEP_SIZE)
        
        csv_sim_irr = world.start(
            'CSV_Irr',
            sim_start=START_DATE,
            datafile=IRRADIANCE_CONT)
        
        csv_sim_temp = world.start(
            'CSV_Temp',
            sim_start=START_DATE,
            datafile=TEMPERATURE_CONT)

        collector = world.start(
            'Collector',
            start_date=START_DATE,
            output_file=ARQUIVO_RESULTADOS_CSV_CONT,
            print_results=False
        )

        print("Instanciando a Grid do OpenDSS...")
        grid = dss_sim.Grid()
        csv_data_irr = csv_sim_irr.Data.create(1)
        csv_data_temp = csv_sim_temp.Data.create(1)
        monitor = collector.Monitor()

        pv_info = dss_sim.get_detected_pvsystems()
        pvs_dss_map = {e.eid: e for e in grid.children if e.type == 'PVSystem'}

        # ====================================================================
        # ALGORITMO DE INSTANCIAÇÃO E CONEXÃO DO SMART INVERTER
        # ====================================================================
        # Mapeamos também as barras para coletar as tensões de medição (Malha Fechada)
        buses_map = {e.eid: e for e in grid.children if e.type == 'Bus'}

        for info in pv_info:
            pv_name = info['name']
            eid_dss = info['eid_dss']
            bus_full = info.get('bus', '')
            bus_base = bus_full.split('.')[0]

            if eid_dss in pvs_dss_map:
                pv_dss_obj = pvs_dss_map[eid_dss]
                bus_eid = f"Bus-{bus_base}"
                
                if bus_eid not in buses_map:
                    print(f"[AVISO] Barramento {bus_eid} não encontrado para realimentação de tensão!")
                    continue
                bus_obj = buses_map[bus_eid]

                # 1. Instancia o Painel Físico (DC)
                pv_panel_obj = pv_sim.PVPanel.create(
                    1,
                    P_mpp=info['pmpp'],
                    irradiance_base=1.0,
                    pt_curve_x=info['pt_curve_x'],
                    pt_curve_y=info['pt_curve_y'],
                    bus_name=bus_base
                )[0]

                # 2. Instancia o Smart Inverter (Adaptado sem os parâmetros antigos)
                inv_obj = inv_sim.Inverter.create(
                    1,
                    kVA=info['kva'],
                    phase_mode='AVG', # Define o modo de fase compatível com inversores individuais
                    eff_curve_x=info['eff_curve_x'],
                    eff_curve_y=info['eff_curve_y'],
                    ctrl_config={'Volt_Var': False, 'Const_PF': False}, # Configuração de controle exigida pelo novo simulador
                    bus_name=bus_base
                )[0]

                # 3. Conexões Climáticas e Lado DC

                # Lê os cabeçalhos removendo a coluna de tempo (antiga ou nova)
                cols_irr = [c for c in pd.read_csv(DATA_DIR_HOST / "ieee13_shape_pv_5min.csv", nrows=0).columns if c.lower() != 'time']
                cols_tmp = [c for c in pd.read_csv(DATA_DIR_HOST / "ieee13_temperature_5min.csv", nrows=0).columns if c.lower() != 'time']
                
                is_dynamic = len(cols_irr) > 1

                if is_dynamic:
                    # Se pv_name for "PV1", extraímos o número "1" para mapear a coluna certa do CSV
                    pv_number = ''.join(filter(str.isdigit, pv_name))
                    # Monta o nome exato das colunas geradas no arquivo CSV consolidado
                    col_irrad = f"my_shape{pv_number}_irrad"
                    col_temp = f"my_shape{pv_number}_temperature"
                else:
                    # Se não é dinâmico, só existe uma coluna de dados disponível em cada arquivo
                    col_irrad = cols_irr[0]
                    col_temp = cols_tmp[0]

                # Conecta ao respectivo painel
                world.connect(csv_data_irr[0], pv_panel_obj, (col_irrad, 'irradiance'))
                world.connect(csv_data_temp[0], pv_panel_obj, (col_temp, 'temperature'))
                # Mantém a conexão DC para o Inversor
                world.connect(pv_panel_obj, inv_obj, ('P_dc', 'P_dc'))

                # 4. FECHAMENTO DE MALHA: Envia as medições de tensão do OpenDSS para o Inversor
                # Usamos time_shifted=True para evitar impasses de execução (deadlocks) entre os simuladores
                world.connect(bus_obj, inv_obj,
                              ('V1_pu', 'V_meas_1'), ('V2_pu', 'V_meas_2'), ('V3_pu', 'V_meas_3'),
                              time_shifted=True,
                              initial_data={'V1_pu': 1.0, 'V2_pu': 1.0, 'V3_pu': 1.0})

                # 5. RETORNO AC: Envia as potências processadas pelo inversor de volta ao OpenDSS
                world.connect(inv_obj, pv_dss_obj, ('P_ac', 'P_des'), ('Q_ac', 'Q_des'))

                # 6. Monitoramento dos Resultados
                world.connect(pv_panel_obj, monitor, 'irradiance', 'temperature', 'P_dc')
                world.connect(inv_obj, monitor, 'P_ac', 'Q_ac')
                world.connect(pv_dss_obj, monitor, 'P_meas', 'Q_meas')
                world.connect(pv_dss_obj, monitor, 'P1', 'P2', 'P3', 'Q1', 'Q2', 'Q3')


        # ====================================================================
        # MONITORES DE TODAS AS BARRAS (CSV)
        # ====================================================================
        print("Conectando todas as barras ao monitor...")
        todas_as_barras = [e for e in grid.children if e.type == 'Bus']
        connect_many_to_one(world, todas_as_barras, monitor, 'V1_pu', 'V2_pu', 'V3_pu')

        # ====================================================================
        # MONITORES DE TODAS AS LINHAS (Corrente e Potência)
        # ====================================================================
        print("Conectando todas as linhas ao monitor...")
        todas_as_linhas = [e for e in grid.children if e.type == 'Line']
        
        connect_many_to_one(
            world, 
            todas_as_linhas, 
            monitor, 
            'I1_A', 'I1_ang', 'I2_A', 'I2_ang', 'I3_A', 'I3_ang',
            'P1_w', 'Q1_var', 'P2_w', 'Q2_var', 'P3_w', 'Q3_var'
        )

        print(f"\nInicializando simulação de {N_PASSOS} para (Step={STEP_SIZE}...)")

        world.run(until=END_TIME, print_progress=False)
        print("Simulação concluída.")

        # --- Check Rápido ---
        if ARQUIVO_RESULTADOS_CSV_HOST.exists():
            print(f"\nResultados salvos em: {ARQUIVO_RESULTADOS_CSV_HOST}")

# ==============================================================================
# GERA ARQUIVO JSON DA REDE
# ==============================================================================

print("Gerando topologia do cenário LV Test Case...")
exportar_topologia(CIRCUITO_DSS_HOST, JSON_SAIDA)

if __name__ == '__main__':
    run_scenario()