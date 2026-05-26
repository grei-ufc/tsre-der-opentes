import pandas as pd
from pathlib import Path

# --- CONFIGURAÇÃO EXCLUSIVA PARA FUNCIONAR NO WSL (NAVEGADOR) ---
import matplotlib
matplotlib.use('WebAgg') 
import matplotlib.pyplot as plt
# ----------------------------------------------------------------

# ==============================================================================
# 1. CONFIGURAÇÃO DE CAMINHOS (ALINHADO COM SEU SCRIPT DE SIMULAÇÃO)
# ==============================================================================
CURRENT_DIR = Path(__file__).parent.resolve()  # src/scenarios
PROJECT_ROOT = CURRENT_DIR.parent.parent 

DATA_DIR_HOST = PROJECT_ROOT / "src" / "data" / "13Bus"
OUTPUT_DIR_HOST = PROJECT_ROOT / "output"

# Arquivos de Entrada (Clima)
CSV_IRRAD_IN = DATA_DIR_HOST / "ieee13_shape_pv_5min.csv"
CSV_TEMP_IN = DATA_DIR_HOST / "ieee13_temperature_5min.csv"

# Arquivo de Saída (Resultados Elétricos)
RESULT_CSV = OUTPUT_DIR_HOST / 'result_run_ieee13_cosim_pv_5min.csv'

def plot_comprehensive_results():
    """
    Plots Irradiance and Temperature directly from input database CSVs, 
    and Active Power / Voltages from Mosaik output CSV.
    """
    # --- VERIFICAÇÃO DE ARQUIVOS ---
    errors = False
    for p in [CSV_IRRAD_IN, CSV_TEMP_IN, RESULT_CSV]:
        if not p.exists():
            print(f"[ERROR]: File not found at:\n{p}")
            errors = True
    if errors:
        return

    print("Loading datasets...")
    df_irr = pd.read_csv(CSV_IRRAD_IN)
    df_tmp = pd.read_csv(CSV_TEMP_IN)
    df_res = pd.read_csv(RESULT_CSV)
    
    if df_res.empty:
        print("[ERROR]: The results file is empty.")
        return

    # --- STEP 2: FILTER ELECTRICAL COLUMNS FROM SIMULATION ---
    pac_columns = [col for col in df_res.columns if 'P_ac' in col]
    raw_vpu_columns = [col for col in df_res.columns if 'V1_pu' in col or 'V2_pu' in col or 'V3_pu' in col]
    vpu_columns = [col for col in raw_vpu_columns if df_res[col].mean() > 0.5]

    # --- STEP 3: MULTI-PLOT GRAPHICS ENGINE ---
    fig, axs = plt.subplots(4, 1, figsize=(14, 12), sharex=True)
    fig.suptitle("Co-Simulation Dashboard\n(Input CSV Weather vs. Output Active Power & Voltages)", fontsize=16, fontweight='bold')

    # Plot 1: Irradiance (Direct from Input CSV)
    # Ignores timestamp columns if present to plot only shapes
    irr_cols = [c for c in df_irr.columns if c.lower() not in ['time', 'timestamp', 'date', 'index']]
    for col in irr_cols:
        label = col.replace('my_shape', 'PV ').replace('_irrad', '')
        axs[0].plot(df_irr.index, df_irr[col], label=label, linewidth=2)
    axs[0].set_title("Input Solar Irradiance Profiles (Source: ieee13_shape_pv_5min.csv)", fontsize=11, fontweight='bold')
    axs[0].set_ylabel("Irradiance\n[W/m² or pu]")
    axs[0].grid(True, linestyle='--', alpha=0.5)
    axs[0].legend(loc="upper right", fontsize=8, frameon=True)

    # Plot 2: Temperature (Direct from Input CSV)
    tmp_cols = [c for c in df_tmp.columns if c.lower() not in ['time', 'timestamp', 'date', 'index']]
    for col in tmp_cols:
        label = col.replace('my_shape', 'PV ').replace('_temperature', '')
        axs[1].plot(df_tmp.index, df_tmp[col], label=label, linewidth=2)
    axs[1].set_title("Input Module Temperature Profiles (Source: ieee13_temperature_5min.csv)", fontsize=11, fontweight='bold')
    axs[1].set_ylabel("Temperature\n[°C or pu]")
    axs[1].grid(True, linestyle='--', alpha=0.5)
    axs[1].legend(loc="upper right", fontsize=8, frameon=True)

    # Plot 3: Active Power (P_ac - from Simulation)
    for col in pac_columns:
        label = col.replace('.P_ac', '').replace('InverterSim-', 'Inverter ')
        axs[2].plot(df_res.index, df_res[col], label=label, linewidth=2)
    axs[2].set_title("Smart Inverters - Active Power Output ($P_{ac}$)", fontsize=11, fontweight='bold')
    axs[2].set_ylabel("Power\n[kW or W]")
    axs[2].grid(True, linestyle='--', alpha=0.5)
    axs[2].legend(loc="upper right", fontsize=8, frameon=True)

    # Plot 4: Voltage Profiles (V_pu - from Simulation)
    for col in vpu_columns:
        label = col.replace('Bus-', 'Bus ').replace('.V1_pu', ' - Ph A').replace('.V2_pu', ' - Ph B').replace('.V3_pu', ' - Ph C')
        axs[3].plot(df_res.index, df_res[col], label=label, linewidth=1.5, linestyle='-.')
    axs[3].set_title("Network Voltage Profiles ($V_{pu}$)", fontsize=11, fontweight='bold')
    axs[3].set_xlabel("Simulation Steps (5-minute intervals)", fontsize=12)
    axs[3].set_ylabel("Voltage\n[pu]")
    axs[3].set_ylim(0.85, 1.10)
    axs[3].grid(True, linestyle='--', alpha=0.5)
    axs[3].legend(loc="lower left", fontsize=8, ncol=4, frameon=True)

    plt.tight_layout()

    # --- STEP 4: RENDER VISUALIZATION ---
    print("\nOpening comprehensive weather-electrical chart in your web browser...")
    plt.show()

if __name__ == '__main__':
    plot_comprehensive_results()