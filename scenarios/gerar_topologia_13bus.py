from pathlib import Path

from simulators.util.topologia import exportar_topologia

# --- Definicao Dinamica de Caminhos ---
CURRENT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = CURRENT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data" / "13Bus"

DSS_13BUS = str(DATA_DIR / "run_ieee13_cosim_pv_5min.dss")  # Caminho do master DSS
JSON_SAIDA = str(DATA_DIR / "topologia_13bus.json")

# Executa a funcao
print("Gerando topologia do cenario 13 barras...")
exportar_topologia(DSS_13BUS, JSON_SAIDA)
