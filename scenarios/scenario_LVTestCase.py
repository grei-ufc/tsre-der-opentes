import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import mosaik
import pandas as pd
from mosaik.util import connect_many_to_one

from simulators.inverter.config import ControlConfig, ReactiveMode, VoltVarCurve
from simulators.util.topologia import exportar_topologia

# ==============================================================================
# CONFIGURAÇÃO DE CONTROLE INTELIGENTE (VOLT-VAR PADRÃO IEEE 1547-2018 CAT. B)
# Amortecimento numérico com olrt=1200s (fator de relaxação suave para passo de 300s)
# ==============================================================================
CTRL_CONFIG_VOLT_VAR = ControlConfig(
    reactive_mode=ReactiveMode.VOLT_VAR,
    volt_var=VoltVarCurve.ieee1547_cat_b(olrt=1200.0),
    trip_enabled=False,
)

# ==============================================================================
# 1. CAMINHOS LOCAIS
# ==============================================================================
CURRENT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = CURRENT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data" / "LVTestCase"
CIRCUITO_DSS = DATA_DIR / "run_LVTestCase.dss"
IRRADIANCE_CSV = DATA_DIR / "LVTestCase_shape_pv_5min.csv"
TEMPERATURE_CSV = DATA_DIR / "LVTestCase_temperature_5min.csv"

OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
ARQUIVO_RESULTADOS_CSV = OUTPUT_DIR / "result_run_LVTestCase.csv"
JSON_SAIDA = str(OUTPUT_DIR / "topologia_LVTestCase.json")

START_DATE = "2026-01-01 00:00:00"
STEP_SIZE = 60 * 5
N_PASSOS = 288
END_TIME = N_PASSOS * STEP_SIZE

# ==============================================================================
# 2. CONFIGURAÇÃO DOS SIMULADORES (EXECUÇÃO LOCAL SEM DOCKER)
# ==============================================================================
SIM_CONFIG = {
    "DSS": {
        "python": "simulators.opendss.api_opendss:OpenDSSSimulator",
    },
    "PVSimulator": {
        "python": "simulators.pv.pv_panel_simulator:PVPanelSim",
    },
    "InverterSim": {
        "python": "simulators.inverter.smart_inverter_simulator:SmartInverterSim",
    },
    "CSV_Irr": {
        "python": "simulators.collector.csv_sim_pandas:CSV",
    },
    "CSV_Temp": {
        "python": "simulators.collector.csv_sim_pandas:CSV",
    },
    "Collector": {
        "python": "simulators.collector.collector:Collector",
    },
}


def _run_scenario_sync(
    output_csv: Path | str | None = None,
    dss_file: Path | str | None = None,
    export_topo: bool = True,
    enable_volt_var: bool = True,
):
    target_dss = Path(dss_file) if dss_file is not None else CIRCUITO_DSS
    out_csv = Path(output_csv) if output_csv is not None else ARQUIVO_RESULTADOS_CSV
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    ctrl_cfg = (
        CTRL_CONFIG_VOLT_VAR
        if enable_volt_var
        else ControlConfig(reactive_mode=ReactiveMode.NONE, trip_enabled=False)
    )

    if not target_dss.exists():
        print(f"[ERRO]: Arquivo DSS não encontrado em:\n{target_dss}")
        return None

    if export_topo:
        print("Gerando topologia do cenário LV Test Case...")
        exportar_topologia(target_dss, JSON_SAIDA)

    with mosaik.World(SIM_CONFIG) as world:
        print("--- Inicializando Simuladores Localmente ---")

        # 1. Iniciando Simuladores Localmente
        dss_sim = world.start(
            "DSS",
            topofile=str(target_dss),
            step_size=STEP_SIZE,
            fail_on_error=False,
            max_iterations=150,
        )

        pv_sim = world.start("PVSimulator", step_size=STEP_SIZE)

        inv_sim = world.start("InverterSim", step_size=STEP_SIZE)

        csv_sim_irr = world.start("CSV_Irr", sim_start=START_DATE, datafile=str(IRRADIANCE_CSV))

        csv_sim_temp = world.start("CSV_Temp", sim_start=START_DATE, datafile=str(TEMPERATURE_CSV))

        collector = world.start(
            "Collector",
            start_date=START_DATE,
            output_file=str(out_csv),
            print_results=False,
        )

        print("Instanciando a Grid do OpenDSS...")
        grid = dss_sim.Grid()
        csv_data_irr = csv_sim_irr.Data.create(1)
        csv_data_temp = csv_sim_temp.Data.create(1)
        monitor = collector.Monitor()

        pv_info = dss_sim.get_detected_pvsystems()
        pvs_dss_map = {e.eid: e for e in grid.children if e.type == "PVSystem"}

        # ====================================================================
        # ALGORITMO DE INSTANCIAÇÃO E CONEXÃO DO SMART INVERTER
        # ====================================================================
        # Mapeamos também as barras para coletar as tensões de medição (Malha Fechada)
        buses_map = {e.eid: e for e in grid.children if e.type == "Bus"}

        cols_irr = [
            c
            for c in pd.read_csv(IRRADIANCE_CSV, nrows=0).columns
            if c.lower() not in ["time", "date"]
        ]
        cols_tmp = [
            c
            for c in pd.read_csv(TEMPERATURE_CSV, nrows=0).columns
            if c.lower() not in ["time", "date"]
        ]
        is_dynamic = len(cols_irr) > 1

        for info in pv_info:
            pv_name = info["name"]
            eid_dss = info["eid_dss"]
            bus_full = info.get("bus", "")
            bus_base = bus_full.split(".")[0]

            if eid_dss in pvs_dss_map:
                pv_dss_obj = pvs_dss_map[eid_dss]
                bus_eid = f"Bus-{bus_base}"

                if bus_eid not in buses_map:
                    print(
                        f"[AVISO] Barramento {bus_eid} não encontrado para realimentação de tensão!"
                    )
                    continue
                bus_obj = buses_map[bus_eid]

                # 1. Instancia o Painel Físico (DC)
                pv_panel_obj = pv_sim.PVPanel.create(
                    1,
                    P_mpp=info["pmpp"],
                    irradiance_base=1.0,
                    pt_curve_x=info["pt_curve_x"],
                    pt_curve_y=info["pt_curve_y"],
                    bus_name=bus_base,
                )[0]

                pv_phases = int(info.get("phases", 1))
                pv_nodes = [n for n in info.get("nodes", [1]) if n in (1, 2, 3)]
                pv_node = (
                    pv_nodes[0]
                    if (pv_phases == 1 and pv_nodes)
                    else (1 if pv_phases == 1 else None)
                )

                # 2. Instancia o Smart Inverter (suporte a monofásico e trifásico BT com Volt-Var ativo)
                inv_obj = inv_sim.Inverter.create(
                    1,
                    kVA=info["kva"],
                    kv=info.get("kv"),
                    phases=pv_phases,
                    node=pv_node,
                    eff_curve_x=info["eff_curve_x"],
                    eff_curve_y=info["eff_curve_y"],
                    ctrl_config=ctrl_cfg,  # Controle Volt-Var ativo
                    bus_name=bus_base,
                )[0]

                # 3. Conexões Climáticas e Lado DC
                if is_dynamic:
                    # Se pv_name for "PV1", extraímos o número "1" para mapear a coluna certa do CSV
                    pv_number = "".join(filter(str.isdigit, pv_name))
                    # Monta o nome exato das colunas geradas no arquivo CSV consolidado
                    col_irrad = f"my_shape{pv_number}_irrad"
                    col_temp = f"my_shape{pv_number}_temperature"
                else:
                    # Se não é dinâmico, só existe uma coluna de dados disponível em cada arquivo
                    col_irrad = cols_irr[0]
                    col_temp = cols_tmp[0]

                # Conecta ao respectivo painel
                world.connect(csv_data_irr[0], pv_panel_obj, (col_irrad, "irradiance"))
                world.connect(csv_data_temp[0], pv_panel_obj, (col_temp, "temperature"))
                # Mantém a conexão DC para o Inversor
                world.connect(pv_panel_obj, inv_obj, ("P_dc", "P_dc"))

                # 4. FECHAMENTO DE MALHA: Envia as medições de tensão do OpenDSS para o Inversor
                # Usamos time_shifted=True para evitar impasses de execução (deadlocks) entre os simuladores
                world.connect(
                    bus_obj,
                    inv_obj,
                    ("V1_pu", "V_meas_1"),
                    ("V2_pu", "V_meas_2"),
                    ("V3_pu", "V_meas_3"),
                    time_shifted=True,
                    initial_data={"V1_pu": 1.0, "V2_pu": 1.0, "V3_pu": 1.0},
                )

                # 5. RETORNO AC: Envia as potências processadas pelo inversor de volta ao OpenDSS
                world.connect(inv_obj, pv_dss_obj, ("P_ac", "P_des"), ("Q_ac", "Q_des"))

                # 6. Monitoramento dos Resultados
                world.connect(pv_panel_obj, monitor, "irradiance", "temperature", "P_dc")
                world.connect(inv_obj, monitor, "P_ac", "Q_ac")
                world.connect(pv_dss_obj, monitor, "P_meas", "Q_meas")
                world.connect(pv_dss_obj, monitor, "P1", "P2", "P3", "Q1", "Q2", "Q3")

        # ====================================================================
        # MONITORES DE TODAS AS BARRAS (CSV)
        # ====================================================================
        print("Conectando todas as barras ao monitor...")
        todas_as_barras = [e for e in grid.children if e.type == "Bus"]
        connect_many_to_one(world, todas_as_barras, monitor, "V1_pu", "V2_pu", "V3_pu")

        # Monitorar Linha LINE1
        target_name = "LINE1"
        target_eid = f"Line-{target_name}"
        line_entities = [e for e in grid.children if e.eid.lower() == target_eid.lower()]
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
            print(f"Monitorando Linha: {target_eid}")

        print(f"\nInicializando simulação de {N_PASSOS} para (Step={STEP_SIZE}...)")

        world.run(until=END_TIME, print_progress=False)
        print("Simulação concluída.")

        # --- Check Rápido ---
        if out_csv.exists():
            print(f"\nResultados salvos em: {out_csv}")
        return out_csv


def run_scenario(
    output_csv: Path | str | None = None,
    dss_file: Path | str | None = None,
    export_topo: bool = True,
    enable_volt_var: bool = True,
):
    """Executa o cenário Mosaik + OpenDSS mesmo quando chamado dentro de um loop asyncio (ex.: Jupyter)."""
    try:
        loop_running = asyncio.get_running_loop() is not None
    except RuntimeError:
        loop_running = False

    if loop_running:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                _run_scenario_sync,
                output_csv=output_csv,
                dss_file=dss_file,
                export_topo=export_topo,
                enable_volt_var=enable_volt_var,
            )
            return future.result()
    return _run_scenario_sync(
        output_csv=output_csv,
        dss_file=dss_file,
        export_topo=export_topo,
        enable_volt_var=enable_volt_var,
    )


if __name__ == "__main__":
    run_scenario()
