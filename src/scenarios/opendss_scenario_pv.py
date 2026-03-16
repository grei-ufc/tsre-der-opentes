import mosaik
from pathlib import Path
import py_dss_interface

# --- CONFIGURAÇÃO DE CAMINHOS ---
CURRENT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = CURRENT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data" / "teste-pv"
IRRADIANCE = DATA_DIR / "irradiance.csv"
TEMPERATURE = DATA_DIR / "temperature.csv"
CIRCUITO_DSS = DATA_DIR / "main.dss"
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
ARQUIVO_RESULTADOS_CSV = OUTPUT_DIR / 'result_opendss_pv.csv'

# --- PARÂMETROS DE TEMPO ---
STEP_SIZE = 60 * 60 # 1 hora em segundos
N_PASSOS = 24
END_TIME = N_PASSOS * STEP_SIZE
START = '2026-01-01 00:00:00'  

SIM_CONFIG = {
    'CSV': {
        'python': 'simulators.csv_sim_pandas:CSV' 
    },
    'PVSimulator': {
        'python': 'simulators.pv_panel_simulator:PVPanelSim' 
    },
    'InverterSim': {
        'python': 'simulators.inverter_simulator:InverterSim'
    },
    'OpenDSS': {
        'python': 'simulators.api_opendss:OpenDSSSimulator' 
    },
    'Collector': {
        'python': 'simulators.collector:Collector' 
    }
}

def get_opendss_pv_parameters(dss_file_path):
    """
    Realiza a descoberta da topologia do OpenDSS para extrair os 
    parâmetros reais (Pmpp e kVA) de todos os PVSystems definidos.
    """
    print(">> Extraindo parâmetros nativos do OpenDSS...")
    dss = py_dss_interface.DSS()
    dss.text("Clear")
    dss.text(f"Compile [{dss_file_path}]")
    
    pv_params = {}
    pv_names = dss.pvsystems.names
    
    # Se retornar ['NONE'] significa que não há PVs
    if pv_names and pv_names[0].upper() != 'NONE':
        for name in pv_names:
            dss.pvsystems.name = name
            pv_params[name] = {
                'pmpp': dss.pvsystems.pmpp,
                'kva': dss.pvsystems.kva
            }
            print(f"   - Encontrado PVSystem.{name} | Pmpp: {dss.pvsystems.pmpp} kW | kVA: {dss.pvsystems.kva}")
    else:
        print("   - Nenhum PVSystem encontrado no circuito.")
        
    return pv_params

def main():
    # 1. Descoberta de Topologia e Parâmetros
    pv_params_dict = get_opendss_pv_parameters(str(CIRCUITO_DSS))

    # 2. Inicialização do Mosaik
    world = mosaik.World(SIM_CONFIG)

    dss_sim = world.start('OpenDSS', step_size=STEP_SIZE, topofile=str(CIRCUITO_DSS), time_resolution=1.0)
    pv_sim = world.start('PVSimulator', step_size=STEP_SIZE)
    inv_sim = world.start('InverterSim', step_size=STEP_SIZE)
    csv_sim_irr = world.start('CSV', sim_start=START, datafile=str(IRRADIANCE))
    csv_sim_temp = world.start('CSV', sim_start=START, datafile=str(TEMPERATURE))
    collector = world.start('Collector', time_resolution=STEP_SIZE, start_date=START, output_file=str(ARQUIVO_RESULTADOS_CSV))

    # 3. Instanciar Entidades (Grid e CSVs que são únicos)
    grid = dss_sim.Grid()
    csv_data_irr = csv_sim_irr.Data.create(1)
    csv_data_temp = csv_sim_temp.Data.create(1)
    monitor = collector.Monitor()

    # Achar as referências da rede do OpenDSS
    buses = [e for e in grid.children if e.type == 'Bus']
    
    # Mapeia os elementos do OpenDSS pelo nome (ex: tira o prefixo 'PVSystem-')
    pvs_dss_map = {e.eid.split('-')[1]: e for e in grid.children if e.type == 'PVSystem'}

    # 4. Criação Dinâmica e Conexões para cada PVSystem encontrado
    for pv_name, params in pv_params_dict.items():
        if pv_name in pvs_dss_map:
            pv_dss_obj = pvs_dss_map[pv_name]
            
            # Instancia as camadas CA e CC dinamicamente com os dados extraídos!
            pv_panel_obj = pv_sim.PVPanel.create(1, P_mpp=params['pmpp'], irradiance_base=0.8,
                                                 pt_curve_x=[0.0, 25.0, 75.0, 100.0],
                                                 pt_curve_y=[1.2, 1.0, 0.8, 0.6])[0]
            inv_obj = inv_sim.Inverter.create(1, kVA=params['kva'], priority='Active',
                                              eff_curve_x=[0.10, 0.20, 0.40, 1.00],
                                              eff_curve_y=[0.86, 0.90, 0.93, 0.97])[0]
            
            # --- Conexões Climáticas ---
            world.connect(csv_data_irr[0], pv_panel_obj, ('irradiance', 'irradiance'))
            world.connect(csv_data_temp[0], pv_panel_obj, ('temperature', 'temperature'))

            # --- Conexões Físicas ---
            world.connect(pv_panel_obj, inv_obj, ('P_dc', 'P_dc'))
            world.connect(inv_obj, pv_dss_obj, ('P_ac', 'P_des'), ('Q_ac', 'Q_des'))

            # --- Monitoramento da Cadeia do PV ---
            # Adiciona um alias para o monitor não misturar caso existam múltiplos PVs
            world.connect(pv_panel_obj, monitor, 'irradiance', 'temperature', 'P_dc')
            world.connect(inv_obj, monitor, 'P_ac', 'Q_ac')
            world.connect(pv_dss_obj, monitor, 'P_meas', 'Q_meas')
        else:
            print(f"AVISO: O PVSystem.{pv_name} foi encontrado no arquivo base, mas não foi retornado pela api_opendss.")

    # Monitoramento de Tensão em Barras
    # for bus in buses:
    #     world.connect(bus, monitor, 'V1_pu', 'V2_pu', 'V3_pu')

    # 5. Rodar Simulação
    print(f"\nIniciando Co-simulação Mosaik para PV em {N_PASSOS} passos...")
    world.run(until=END_TIME)
    print(f"Simulação concluída! Resultados salvos em: {ARQUIVO_RESULTADOS_CSV}")

if __name__ == '__main__':
    main()