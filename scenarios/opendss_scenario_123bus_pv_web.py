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

O que cada cor significa está em :data:`ETYPES`. Os botões no canto superior
direito trocam a fase mostrada, e valem para todos os tipos ao mesmo tempo: em
``A``, as barras mostram a tensão da fase A e o PV mostra a potência que injeta
nessa mesma fase.

As 91 cargas ficam fora do desenho. O IEEE123 é denso: ajustado à janela, o vão
mediano entre barras vizinhas é de ~48 px, menor que o anel de ~34-50 px em que
cada carga sem coordenada é semeada em volta da sua barra — ou seja, cada carga
cai dentro do território da barra do lado. Sem elas restam as 132 barras, o PV e
os 7 reguladores, e o traçado do alimentador fica legível. Para voltar a
desenhá-las, tire ``"Load"`` de ``ignore_types`` e devolva a entrada ao
:data:`ETYPES` (o cenário ``opendss_scenario_123bus_web.py`` tem uma pronta).

Ao contrário de ``opendss_scenario_123bus_pv.py``, este cenário não grava CSV —
é para olhar, não para medir. Use o outro quando quiser os dados em disco.
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

# Cada entrada diz o que o tipo publica para o desenho e como aquilo vira cor.
# A chave tem de casar com o `type` que o adaptador registra (os nomes de
# MODEL_SPECS em element_specs.py), e as escalas `min`/`max` sao deste circuito:
# recalibre-as ao trocar de alimentador.
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
    # "Load" nao entra aqui de proposito: as cargas sao removidas do desenho
    # por `ignore_types` (ver connect_visualization). Manter a entrada faria o
    # laco abaixo conectar 91 dataflows por passo que ninguem desenha, e poria
    # na legenda um tipo que nao aparece na tela — a legenda e montada a partir
    # deste dicionario, nao dos nos.
    "PVSystem": {
        # Verde no CSS, para o gerador se distinguir da carga a olho.
        "cls": "gen",
        # Em pu da placa do proprio inversor, e nao em kW: uma escala de cor e
        # compartilhada por todos os PVs do alimentador, entao em kW um PV
        # pequeno ficaria verde o dia inteiro ao lado de um grande. Em pu,
        # qualquer inversor a plena geracao marca 1.0. Por fase, para o PV
        # responder aos mesmos botoes de fase que as barras.
        "attrs": ["P1_pu", "P2_pu", "P3_pu"],
        "series": ["A", "B", "C"],
        "aggregate": "mean",
        "unit": "P [pu da placa]",
        "default": 0,
        # Fixo, e nao calibrado neste circuito: em pu a faixa vale para
        # qualquer alimentador.
        "min": 0,
        "max": 1.0,
        # Injetar e positivo (PV_SIGN no element_specs). A noite a geracao e
        # zero e o no fica cinza (`ignore_zero` vale por padrao quando ha mais
        # de um atributo), o que se le como "nao esta gerando".
        "radius": 7,
    },
    "Storage": {
        # Roxo no CSS. Este circuito nao tem bateria, entao o tipo fica sem
        # entidade nenhuma e e ignorado pelo laco de conexao; esta aqui para
        # quando o alimentador tiver uma.
        "cls": "storage",
        # O estado de carga e o que se quer olhar numa bateria, e ja vem em pu.
        # Atencao a direcao da cor: com `min=0` o frontend pinta o fundo da
        # escala de verde e o topo de vermelho, ou seja, bateria cheia aparece
        # vermelha. Para ver carga/descarga em vez do estado, troque por
        # `["P_act"]` com min=-max (kW, positivo = descarregando).
        "attrs": ["SoC"],
        "unit": "SoC [pu]",
        "default": 0,
        "min": 0,
        "max": 1.0,
        "radius": 7,
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
        connect_visualization(world, dss_sim, webvis, children)

        print(f"\nAbra o navegador em http://{WEB_HOST}:{WEB_PORT}/ e aguarde o primeiro passo.")
        world.run(until=END_TIME, rt_factor=RT_FACTOR, print_progress=False)
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


def connect_visualization(world, dss_sim, webvis, children):
    """Liga as entidades do circuito à topologia desenhada no navegador."""
    webvis.set_config(
        # O webvis desenha *todas* as entidades da simulação, não só as do
        # circuito: sem esta lista, o painel, o inversor, os CSVs e os
        # controladores virariam nós pendurados no alimentador.
        #
        # É aqui, e não no ETYPES, que um tipo some do desenho: a topologia vem
        # de `get_related_entities`, então uma carga fora do ETYPES continuaria
        # desenhada, só que como um círculo cinza sem dado nenhum.
        ignore_types=[
            "Grid",
            "Topology",
            "RegController",
            "PVPanel",
            "Inverter",
            "Data",
            # As 91 cargas encobrem o traçado neste alimentador; ver o
            # docstring do módulo.
            "Load",
        ],
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
