"""IEEE 123 barras com inversores inteligentes (volt-var / volt-watt via OpenDER).

Cada ``PVSystem`` do circuito vira uma unidade de inversor com seu próprio
objeto OpenDER, agrupada por barra em uma entidade mosaik. As unidades
monofásicas de uma mesma barra respondem cada uma à tensão da sua fase, que é
como o padrão IEEE 1547 modela um inversor.
"""

from pathlib import Path

import mosaik

from simulators.inverter.config import (
    ControlConfig,
    InverterUnit,
    ReactiveMode,
    VoltVarCurve,
    VoltWattCurve,
)

# --- Definição Dinâmica de Caminhos ---
CURRENT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = CURRENT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data" / "123Bus"

CIRCUITO_DSS = DATA_DIR / "run_ieee123_cosim_pv_5min.dss"

IRRADIANCE = DATA_DIR / "ieee123_shape_pv_5min.csv"
TEMPERATURE = DATA_DIR / "ieee123_temperature_5min.csv"
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
ARQUIVO_RESULTADOS_CSV = OUTPUT_DIR / "result_run_ieee123_cosim_smart_pv_5min.csv"

START_DATE = "2026-01-01 00:00:00"
STEP_SIZE = 60 * 5
N_PASSOS = 288
END_TIME = N_PASSOS * STEP_SIZE

# ====================================================================
# CONFIGURAÇÃO DO CONTROLE
# ====================================================================
# `olrt` é o filtro de primeira ordem do OpenDER e, aqui, também o
# amortecimento da malha realimentada: a tensão do OpenDSS volta atrasada de um
# passo (`time_shifted=True`), então uma resposta instantânea pode entrar em
# ciclo limite. Com `olrt = 2 * STEP_SIZE` cada passo aplica ~37% da variação
# pedida — o equivalente ao `delta_q=0.2` que o OpenDER_interface da EPRI usa
# ao iterar dentro do passo.
#
# Abaixo de `1.15 * STEP_SIZE` o filtro do OpenDER é curto-circuitado e a
# resposta volta a ser instantânea. Os 600 s ficam acima da faixa de 1-90 s da
# IEEE 1547: é uma escolha numérica deliberada, não um tempo de resposta físico.
OLRT = 2 * STEP_SIZE

CONTROLE = ControlConfig(
    reactive_mode=ReactiveMode.VOLT_VAR,
    volt_var=VoltVarCurve.ieee1547_cat_b(olrt=OLRT),
    volt_watt=VoltWattCurve.ieee1547_default(olrt=OLRT),
    # Com passo de 5 min, um único instante acima de 1.1 pu derrubaria o
    # inversor por ~15 min. Para estudo de capacidade de hospedagem, o trip
    # atrapalha mais do que informa.
    trip_enabled=False,
    priority="REACTIVE",
    v_meas_unbalance="AVG",
)

# --- Configuração dos Simuladores ---
SIM_CONFIG = {
    "DSS": {
        "python": "simulators.opendss.api_opendss:OpenDSSSimulator",
    },
    "PVSimulator": {"python": "simulators.pv.pv_panel_simulator:PVPanelSim"},
    "InverterSim": {"python": "simulators.inverter.smart_inverter_simulator:SmartInverterSim"},
    "CSV": {"python": "simulators.collector.csv_sim_pandas:CSV"},
    "Collector": {
        "python": "simulators.collector.collector:Collector",
    },
}


def _build_units(lista_pvs):
    """Traduz os PVSystems de uma barra em unidades de inversor.

    A topologia já vem resolvida em ``extra_info`` pelo simulador do OpenDSS,
    então não é preciso reconstruí-la por string aqui.
    """
    units = []
    for pv in lista_pvs:
        info = pv.extra_info
        phases = int(info.get("phases") or 3)
        units.append(
            InverterUnit(
                name=info["name"],
                kva=info["kva"],
                kw=info["pmpp"],
                kv=info["kv"],
                phases=phases,
                node=info["nodes"][0] if phases == 1 else None,
            )
        )
    return units


def run_scenario():
    if not CIRCUITO_DSS.exists():
        print(f"[ERRO]: Arquivo DSS não encontrado em:\n{CIRCUITO_DSS}")
        return

    with mosaik.World(SIM_CONFIG) as world:
        print("--- Inicializando Simuladores ---")

        dss_sim = world.start("DSS", topofile=str(CIRCUITO_DSS), step_size=STEP_SIZE)
        pv_sim = world.start("PVSimulator", step_size=STEP_SIZE)
        inv_sim = world.start("InverterSim", step_size=STEP_SIZE)
        csv_sim_irr = world.start("CSV", sim_start=START_DATE, datafile=str(IRRADIANCE))
        csv_sim_temp = world.start("CSV", sim_start=START_DATE, datafile=str(TEMPERATURE))

        collector = world.start(
            "Collector",
            start_date=START_DATE,
            output_file=str(ARQUIVO_RESULTADOS_CSV),
            print_results=False,
        )

        print("Instanciando a Grid do OpenDSS...")
        grid = dss_sim.Grid()
        csv_data_irr = csv_sim_irr.Data.create(1)
        csv_data_temp = csv_sim_temp.Data.create(1)
        monitor = collector.Monitor()

        # ====================================================================
        # AGRUPAMENTO TOPOLÓGICO (por barramento)
        # ====================================================================
        pvs_dss = [e for e in grid.children if e.type == "PVSystem"]
        buses_map = {e.eid: e for e in grid.children if e.type == "Bus"}

        inversores_logicos = {}
        for pv in pvs_dss:
            inversores_logicos.setdefault(pv.extra_info["bus"], []).append(pv)

        print(
            f"\n[OpenTES] Detectados {len(inversores_logicos)} Inversores Lógicos "
            f"baseados na Topologia:"
        )

        # ====================================================================
        # INSTANCIAÇÃO E CONEXÃO
        # ====================================================================
        for bus_base, lista_pvs in inversores_logicos.items():
            bus_eid = f"Bus-{bus_base}"
            if bus_eid not in buses_map:
                print(f"[AVISO] Barramento {bus_eid} não encontrado para monitoramento!")
                continue
            bus_obj = buses_map[bus_eid]

            infos = [pv.extra_info for pv in lista_pvs]
            units = _build_units(lista_pvs)
            pmpp_total = sum(i["pmpp"] for i in infos)
            kva_total = sum(u.kva for u in units)

            print(
                f" -> Barra {bus_base}: {len(units)} PV(s) | {kva_total:.1f} kVA | "
                f"fases {[u.phases for u in units]}"
            )

            # Painel físico (DC) consolidado da barra
            pv_panel_obj = pv_sim.PVPanel.create(
                1,
                P_mpp=pmpp_total,
                irradiance_base=0.8,  # base do OpenDSS
                pt_curve_x=infos[0]["pt_curve_x"],
                pt_curve_y=infos[0]["pt_curve_y"],
            )[0]

            # Inversor inteligente: uma unidade OpenDER por PVSystem.
            # `pct_cutin`/`pct_cutout` vêm do circuito — o simulador do OpenDSS
            # neutraliza as curvas nativas, então o corte é modelado aqui.
            inv_obj = inv_sim.Inverter.create(
                1,
                units=[u.to_dict() for u in units],
                ctrl_config=CONTROLE.to_dict(),
                eff_curve_x=infos[0]["eff_curve_x"],
                eff_curve_y=infos[0]["eff_curve_y"],
                pct_cutin=infos[0]["pct_cutin"],
                pct_cutout=infos[0]["pct_cutout"],
            )[0]

            # Clima -> painel -> inversor
            world.connect(csv_data_irr[0], pv_panel_obj, ("my_shape2_pv", "irradiance"))
            world.connect(csv_data_temp[0], pv_panel_obj, ("temperature", "temperature"))
            world.connect(pv_panel_obj, inv_obj, ("P_dc", "P_dc"))

            # IDA: tensão da barra para o inversor, atrasada de um passo para
            # quebrar o ciclo do grafo de dependências.
            world.connect(
                bus_obj,
                inv_obj,
                ("V1_pu", "V_meas_1"),
                ("V2_pu", "V_meas_2"),
                ("V3_pu", "V_meas_3"),
                time_shifted=True,
                initial_data={"V1_pu": 1.0, "V2_pu": 1.0, "V3_pu": 1.0},
            )

            # VOLTA: injeção de cada unidade para o PVSystem correspondente.
            # `P_ac_k` é a k-ésima unidade na ordem de `units`, que é a mesma
            # de `lista_pvs`.
            for idx, pv_dss_obj in enumerate(lista_pvs, start=1):
                world.connect(
                    inv_obj, pv_dss_obj, (f"P_ac_{idx}", "P_des"), (f"Q_ac_{idx}", "Q_des")
                )
                world.connect(pv_dss_obj, monitor, "P_meas", "Q_meas")

            # Monitoramento: as saídas de diagnóstico são o que permite auditar
            # por que Q vale o que vale em cada passo.
            world.connect(pv_panel_obj, monitor, "irradiance", "temperature", "P_dc")
            world.connect(
                inv_obj,
                monitor,
                "P_ac",
                "Q_ac",
                "V_meas_pu",
                "der_status",
                "q_desired_pu",
                "p_pv_limit_pu",
            )

        # ====================================================================
        # MONITORES GERAIS DA REDE
        # ====================================================================
        for target_name in ["149", "97"]:
            target_eid = f"Bus-{target_name}"
            bus_entities = [e for e in grid.children if e.eid == target_eid]
            if bus_entities:
                world.connect(bus_entities[0], monitor, "V1_pu", "V2_pu", "V3_pu")
                print(f"Monitorando Barra: {target_eid}")

        target_eid = "Line-L115"
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

        print(f"\nInicializando simulação de {N_PASSOS} passos (Step={STEP_SIZE}s)...")
        world.run(until=END_TIME, print_progress=False)
        print("Simulação concluída.")

        if ARQUIVO_RESULTADOS_CSV.exists():
            print(f"\nResultados salvos em: {ARQUIVO_RESULTADOS_CSV}")


if __name__ == "__main__":
    run_scenario()
