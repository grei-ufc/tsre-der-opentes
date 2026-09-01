"""IEEE123 com regulação de tensão em malha fechada e visualização no navegador.

O maior dos alimentadores do projeto na visualização web: 132 barras, 91 cargas
e 7 reguladores de tensão. Cada barra é desenhada nas coordenadas reais do
alimentador, dividida em três setores — um por fase — e colorida pela tensão.

Os botões no canto superior direito trocam o que colore o mapa: ``3φ`` mostra as
três fases ao mesmo tempo, ``A``/``B``/``C`` isolam uma, e ``mín``/``máx``/
``méd``/``desb`` mostram agregações. Clicar num nó abre a linha do tempo com uma
curva por fase.

Duas barras (``300_open`` e ``94_open``) não constam do ``BusCoords.dat`` do
IEEE123 — são artefatos das chaves abertas do circuito. Elas caem no layout de
forças, e é normal vê-las flutuando fora do traçado do alimentador.

O circuito é denso: para um desenho mais limpo, acrescente ``"Load"`` a
``ignore_types`` e as 91 cargas somem, ficando só as barras e os reguladores.
"""

import sys
import warnings
from pathlib import Path

import mosaik
from mosaik.util import connect_many_to_one

# Ver o comentário em opendss_scenario_34bus_web.py: o aviso de "simulation too
# slow" dispara com qualquer atraso positivo, por menor que seja, e não indica
# problema na visualização.
warnings.filterwarnings("ignore", message="Simulation too slow for real-time factor")

CURRENT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = CURRENT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data" / "123Bus"
# Compila o IEEE123Master.dss, que já carrega o BusCoords.dat: as coordenadas
# das barras vêm sem nenhum parâmetro extra.
CIRCUITO_DSS = DATA_DIR / "run_ieee123_cosim_5min.dss"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

START_DATE = "2025-01-01 00:00:00"
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
    "RegControl": {
        "python": "simulators.controller.regulator_control:RegulatorSimulator",
    },
    "WebVis": {
        "python": "simulators.webvis:Simulator",
    },
}

ETYPES = {
    "Bus": {
        "cls": "pqbus",
        "attrs": ["V1_pu", "V2_pu", "V3_pu"],
        "series": ["A", "B", "C"],
        # A fase mais baixa é a que decide se a barra está em conformidade.
        "aggregate": "min",
        "unit": "V [pu]",
        "default": 1.0,
        "min": 0.90,
        "max": 1.10,
        # Escala do botão "desb": 5% de amplitude entre fases já é muito.
        "spread_max": 0.05,
    },
    "Load": {
        "cls": "load",
        "attrs": ["P_out_mw"],
        "unit": "P [MW]",
        "default": 0,
        "min": 0,
        # As cargas pontuais do IEEE123 vão até 40 kW.
        "max": 0.05,
        # Menor que as barras: a carga é o que se pendura na rede, não um ponto
        # dela.
        "radius": 5,
    },
    "RegControl": {
        "cls": "special",
        "attrs": ["tap"],
        "unit": "tap",
        "default": 0,
        "min": -16,
        "max": 16,
        "radius": 6,
    },
}


def run_scenario():
    if not CIRCUITO_DSS.exists():
        print(f"ERRO CRÍTICO: Arquivo DSS não encontrado em:\n{CIRCUITO_DSS}")
        sys.exit(1)

    with mosaik.World(SIM_CONFIG) as world:
        dss_sim = world.start("DSS", topofile=str(CIRCUITO_DSS), step_size=STEP_SIZE)
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

        connect_regulators(world, dss_sim, reg_sim, children)
        connect_visualization(world, dss_sim, webvis, children)

        print(f"\nAbra o navegador em http://{WEB_HOST}:{WEB_PORT}/ e aguarde o primeiro passo.")
        world.run(until=END_TIME, rt_factor=RT_FACTOR, print_progress=False)
        print("Simulação concluída.")


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


def connect_visualization(world, dss_sim, webvis, children):
    """Liga as entidades do circuito à topologia desenhada no navegador."""
    webvis.set_config(
        # O Grid é só o contêiner das entidades, e o RegController é o
        # controlador Python: nenhum dos dois é parte da rede desenhada.
        ignore_types=["Grid", "Topology", "RegController"],
        # Linha e transformador são ligações entre barras, não nós do desenho.
        merge_types=["Line", "Transformer"],
        timeline_hours=24,
    )
    webvis.set_etypes(ETYPES)

    vis_topo = webvis.Topology()

    for model_type, conf in ETYPES.items():
        entities = [e for e in children if e.type == model_type]
        if not entities:
            continue
        connect_many_to_one(world, entities, vis_topo, *conf["attrs"])
        print(f"{len(entities):>3} {model_type} conectadas à visualização")

    positions = dss_sim.get_bus_positions()
    known = {e.full_id: positions[e.eid] for e in children if e.eid in positions}
    webvis.set_node_positions(known)
    print(f"{len(known):>3} barras com coordenada real (as demais ficam no layout de forças)")


if __name__ == "__main__":
    run_scenario()
