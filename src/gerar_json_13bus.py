from simulators.topologia import exportar_topologia
from pathlib import Path

# Configura os caminhos
BASE_DIR = Path(__file__).resolve().parent
DSS_13BUS = str(BASE_DIR / 'data' / '13Bus' / 'run_ieee13_cosim_pv_5min.dss') # Caminho do master DSS
JSON_SAIDA = str(BASE_DIR / 'data' / '13Bus' / 'topologia_13bus.json')

# Executa a função
print("Gerando topologia do cenário 13 barras...")
exportar_topologia(DSS_13BUS, JSON_SAIDA)

