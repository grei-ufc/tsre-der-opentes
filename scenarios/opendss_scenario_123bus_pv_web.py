"""IEEE123 com geração fotovoltaica, regulação de tensão e visualização no navegador.

Junta as duas metades que já existiam separadas: a cadeia de co-simulação
fotovoltaica de ``opendss_scenario_123bus_pv.py`` (irradiância e temperatura de
CSV -> painel -> inversor -> PVSystem do OpenDSS) e o desenho no navegador de
``opendss_scenario_123bus_web.py``.

O circuito é o ``run_ieee123_cosim_pv_5min.dss``, que difere do usado no cenário
web sem PV em dois pontos que se notam no desenho: tem ``Set Loadmult=1.9``, o
que quase dobra todas as cargas, e um PVSystem trifásico de 1 MW na barra 97 —
grande o bastante para inverter o fluxo no ramal ao meio-dia.

Os sete reguladores entram na malha fechada porque o ``.dss`` desliga a atuação
nativa deles (``Batchedit RegControl..* maxtapchange=0``); sem os controladores
Python os taps ficariam congelados enquanto o PV empurra a tensão para cima.

O que é desenhado está em :data:`SHOW`: tensão por fase nas barras, geração em
pu da placa no PV e estado de carga nas baterias. Os botões no canto superior
direito trocam a fase mostrada e valem para todos os tipos ao mesmo tempo: em
``A``, as barras mostram a tensão da fase A e o PV mostra a geração nessa mesma
fase.

Os reguladores continuam em malha fechada, só não aparecem no desenho. As 91
cargas também ficam de fora. O IEEE123 é denso: ajustado à janela, o vão
mediano entre barras vizinhas é de ~48 px, menor que o anel de 34 a 50 px em
que cada carga sem coordenada é semeada em volta da sua barra.

Ao contrário de ``opendss_scenario_123bus_pv.py``, este cenário não grava CSV —
é para olhar, não para medir. Use o outro quando quiser os dados em disco.
"""

import sys
import warnings
from pathlib import Path

import mosaik

from simulators.opendss.visualization import PRESETS, attach_webvis

# Ver o comentário em opendss_scenario_34bus_web.py: o aviso de "simulation too
# slow" dispara com qualquer atraso positivo, por menor que seja, e não indica
# problema na visualização.
warnings.filterwarnings("ignore", message="Simulation too slow for real-time factor")

CURRENT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = CURRENT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data" / "123Bus"
CIRCUITO_DSS = DATA_DIR / "run_ieee123_cosim_pv_5min.dss"
IRRADIANCE = DATA_DIR / "ieee123_shape_pv_5min.csv"
TEMPERATURE = DATA_DIR / "ieee123_temperature_5min.csv"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

START_DATE = "2026-01-01 00:00:00"
STEP_SIZE = 60 * 5
N_PASSOS = 288
END_TIME = N_PASSOS * STEP_SIZE

WEB_HOST = "127.0.0.1"
WEB_PORT = 8000

# Um passo de 5 min a cada 1 s de relógio: o dia inteiro leva ~5 min. Use None
# para rodar o mais rápido possível (o navegador mal terá tempo de conectar).
RT_FACTOR = 1 / 300

SIM_CONFIG = {
    "DSS": {
        "python": "simulators.opendss.api_opendss:OpenDSSSimulator",
    },
    "PVSimulator": {
        "python": "simulators.pv.pv_panel_simulator:PVPanelSim",
    },
    "InverterSim": {
        "python": "simulators.inverter.inverter_simulator:InverterSim",
    },
    "CSV": {
        "python": "simulators.collector.csv_sim_pandas:CSV",
    },
    "RegControl": {
        "python": "simulators.controller.regulator_control:RegulatorSimulator",
    },
    "WebVis": {
        "python": "simulators.webvis:Simulator",
    },
}

# O que aparece no navegador e como cada tipo é colorido. Só os tipos listados
# são desenhados. Para recalibrar um tipo, sobrescreva as chaves do preset:
# {**PRESETS["Bus"], "min": 0.93}.
SHOW = {
    "Bus": PRESETS["Bus"],
    "PVSystem": PRESETS["PVSystem"],
    # Este circuito não tem bateria: o tipo fica sem entidade e não aparece,
    # mas já está pronto para um alimentador que tenha.
    # "Storage": PRESETS["Storage"],
}


def run_scenario():
    for arquivo in (CIRCUITO_DSS, IRRADIANCE, TEMPERATURE):
        if not arquivo.exists():
            print(f"ERRO CRÍTICO: arquivo não encontrado em:\n{arquivo}")
            sys.exit(1)

    with mosaik.World(SIM_CONFIG) as world:
        dss_sim = world.start("DSS", topofile=str(CIRCUITO_DSS), step_size=STEP_SIZE)
        pv_sim = world.start("PVSimulator", step_size=STEP_SIZE)
        inv_sim = world.start("InverterSim", step_size=STEP_SIZE)
        csv_irr = world.start("CSV", sim_start=START_DATE, datafile=str(IRRADIANCE))
        csv_temp = world.start("CSV", sim_start=START_DATE, datafile=str(TEMPERATURE))
        reg_sim = world.start("RegControl", step_size=STEP_SIZE)
        webvis = world.start(
            "WebVis",
            start_date=START_DATE,
            step_size=STEP_SIZE,
            host=WEB_HOST,
            port=WEB_PORT,
        )

        grid = dss_sim.Grid()
        children = list(grid.children)

        connect_pv_chain(world, dss_sim, pv_sim, inv_sim, csv_irr, csv_temp, children)
        connect_regulators(world, dss_sim, reg_sim, children)
        attach_webvis(world, dss_sim, grid, webvis, show=SHOW)

        print(f"\nAbra o navegador em http://{WEB_HOST}:{WEB_PORT}/ e aguarde o primeiro passo.")
        world.run(until=END_TIME, rt_factor=RT_FACTOR, print_progress=True)
        print("Simulação concluída.")


def connect_pv_chain(world, dss_sim, pv_sim, inv_sim, csv_irr, csv_temp, children):
    """Monta painel e inversor para cada PVSystem do circuito e fecha a cadeia.

    O PVSystem do OpenDSS deixa de seguir a própria curva e passa a receber o
    ``P``/``Q`` calculado pelo par painel+inversor, que por sua vez lê a
    irradiância e a temperatura dos CSVs.
    """
    detected = dss_sim.get_detected_pvsystems()

    if not detected:
        print("[AVISO] Nenhum PVSystem detectado no circuito.")
        return

    print(f"[AUTO-SETUP] Configurando {len(detected)} sistemas fotovoltaicos:")

    dados_irr = csv_irr.Data.create(1)[0]
    dados_temp = csv_temp.Data.create(1)[0]
    pvs_por_eid = {e.eid: e for e in children if e.type == "PVSystem"}

    for info in detected:
        eid_dss = info["eid_dss"]
        pv_dss = pvs_por_eid.get(eid_dss)

        if pv_dss is None:
            print(f"  [ERRO] Entidade {eid_dss} não encontrada em grid.children!")
            continue

        painel = pv_sim.PVPanel.create(
            1,
            P_mpp=info["pmpp"],
            irradiance_base=0.8,
            pt_curve_x=info["pt_curve_x"],
            pt_curve_y=info["pt_curve_y"],
        )[0]

        inversor = inv_sim.Inverter.create(
            1,
            kVA=info["kva"],
            priority="Active",
            eff_curve_x=info["eff_curve_x"],
            eff_curve_y=info["eff_curve_y"],
            pct_cutin=info["pct_cutin"],
            pct_cutout=info["pct_cutout"],
        )[0]

        world.connect(dados_irr, painel, ("my_shape2_pv", "irradiance"))
        world.connect(dados_temp, painel, ("temperature", "temperature"))
        world.connect(painel, inversor, ("P_dc", "P_dc"))
        world.connect(inversor, pv_dss, ("P_ac", "P_des"), ("Q_ac", "Q_des"))

        print(f"  -> {info['name']} @ {info['bus']} | Pmpp: {info['pmpp']} kW")


def connect_regulators(world, dss_sim, reg_sim, children):
    """Fecha a malha entre cada RegControl do circuito e seu controlador Python.

    O ``.dss`` do IEEE123 desliga a atuação nativa dos reguladores
    (``Batchedit RegControl..* maxtapchange=0``): sem estes controladores os
    taps ficariam congelados na posição inicial durante o dia inteiro.
    """
    detected = dss_sim.get_detected_regulators()

    if not detected:
        print("[AVISO] Nenhum regulador de tensão detectado no circuito.")
        return

    print(f"[AUTO-SETUP] Configurando {len(detected)} reguladores de tensão:")

    for info in detected:
        eid_dss = info["eid_dss"]
        try:
            dss_entity = next(e for e in children if e.eid == eid_dss)
        except StopIteration:
            print(f"  [ERRO] Entidade {eid_dss} não encontrada em grid.children!")
            continue

        ctrl_entity = reg_sim.RegController(
            vreg=info["vreg"],
            band=info["band"],
            pt_ratio=info["pt_ratio"],
            ct_primary=info.get("ct_primary", 0),
            R=info.get("R", 0),
            X=info.get("X", 0),
            delay=info["delay"],
            tap_delay=info["tap_delay"],
            tap_ini=0,
        )

        # Medição -> controlador (um passo atrás, para quebrar o laço algébrico)
        world.connect(
            dss_entity,
            ctrl_entity,
            ("v_meas", "v_meas"),
            time_shifted=True,
            initial_data={"v_meas": info["vreg"]},
        )
        world.connect(
            dss_entity,
            ctrl_entity,
            ("i_meas", "i_meas"),
            time_shifted=True,
            initial_data={"i_meas": 0},
        )
        # Comando de tap -> circuito
        world.connect(ctrl_entity, dss_entity, ("tap_cmd", "tap"))

        print(f"  -> {info['name']} @ {info['target_bus']}.{info['target_phase']}")


if __name__ == "__main__":
    run_scenario()
