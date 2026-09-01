"""Smoke test da visualização web: IEEE13 com as três tensões de fase.

É o cenário mínimo que exercita o caminho inteiro — grafo de entidades do
OpenDSS -> topologia D3 -> WebSocket -> navegador. Use-o para verificar que a
visualização sobe antes de investigar problemas nos cenários maiores.

Só as barras e as ligações entre elas são desenhadas: cargas e reguladores
ficam de fora para que o que aparece na tela seja exatamente o que este teste
verifica. O IEEE13 já carrega as coordenadas das barras no próprio ``.dss``
(``BusCoords IEEE13Node_BusXY.csv``), então o desenho sai na forma do
alimentador sem nenhum parâmetro extra.
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
DATA_DIR = PROJECT_ROOT / "data" / "13Bus"
CIRCUITO_DSS = DATA_DIR / "IEEE13Nodeckt_w_loadcurve.dss"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

START_DATE = "2025-01-01 00:00:00"
STEP_SIZE = 600
N_PASSOS = 144
END_TIME = N_PASSOS * STEP_SIZE

WEB_HOST = "127.0.0.1"
WEB_PORT = 8000

# Um passo de 600 s a cada 2 s de relógio: a simulação inteira leva ~5 min, o
# suficiente para acompanhar a evolução das tensões no navegador. Use None para
# rodar o mais rápido possível (o navegador mal terá tempo de conectar).
RT_FACTOR = 1 / 300

SIM_CONFIG = {
    "DSS": {
        "python": "simulators.opendss.api_opendss:OpenDSSSimulator",
    },
    "WebVis": {
        "python": "simulators.webvis:Simulator",
    },
}

# As três fases da barra, uma por setor do nó. Com um atributo só — como era
# este cenário antes — não há o que dividir, e o desenho volta a ser um disco.
BUS_ETYPE = {
    "cls": "pqbus",
    "attrs": ["V1_pu", "V2_pu", "V3_pu"],
    "series": ["A", "B", "C"],
    "aggregate": "min",
    "unit": "V [pu]",
    "default": 1.0,
    "min": 0.93,
    "max": 1.05,
    "spread_max": 0.05,
}


def run_scenario():
    if not CIRCUITO_DSS.exists():
        print(f"ERRO CRÍTICO: Arquivo DSS não encontrado em:\n{CIRCUITO_DSS}")
        sys.exit(1)

    with mosaik.World(SIM_CONFIG) as world:
        dss_sim = world.start("DSS", topofile=str(CIRCUITO_DSS), step_size=STEP_SIZE)
        webvis = world.start(
            "WebVis",
            start_date=START_DATE,
            step_size=STEP_SIZE,
            host=WEB_HOST,
            port=WEB_PORT,
        )

        grid = dss_sim.Grid()
        children = list(grid.children)

        webvis.set_config(
            # Cargas e reguladores existem no circuito, mas ficam fora do
            # desenho: aqui interessam as barras e as ligações entre elas.
            ignore_types=["Grid", "Topology", "Load", "RegControl"],
            # Linha e transformador são ligações entre barras, não nós. Sem
            # incluir o transformador, 650 <-> rg60 (reguladores) e 633 <-> 634
            # (XFM1) ficariam sem aresta e o desenho sairia em pedaços.
            merge_types=["Line", "Transformer"],
            timeline_hours=24,
        )
        webvis.set_etypes({"Bus": BUS_ETYPE})
        vis_topo = webvis.Topology()

        buses = [e for e in children if e.type == "Bus"]
        connect_many_to_one(world, buses, vis_topo, *BUS_ETYPE["attrs"])
        print(f"{len(buses)} barras conectadas à visualização.")

        positions = dss_sim.get_bus_positions()
        known = {e.full_id: positions[e.eid] for e in buses if e.eid in positions}
        webvis.set_node_positions(known)
        print(f"{len(known)} barras com coordenada real.")

        print(f"\nAbra o navegador em http://{WEB_HOST}:{WEB_PORT}/ e aguarde o primeiro passo.")
        world.run(until=END_TIME, rt_factor=RT_FACTOR, print_progress=True)
        print("Simulação concluída.")


if __name__ == "__main__":
    run_scenario()
