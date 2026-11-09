"""Cenário de Co-simulação com Veículos Elétricos no Alimentador IEEE 13 Barras
=============================================================================

Executa a co-simulação quase-estática (QSTS) no tempo do alimentador IEEE 13 barras
com a integração estocástica de Veículos Elétricos (VEs) baseados no modelo
eletroquímico C++ Caldera ICM acoplado dinamicamente ao OpenDSS via Mosaik.

Etapas do Cenário:
------------------
1. Alocação estocástica e reprodutível de VEs via Nested Adoption (alocar_evs);
2. Configuração do ambiente Mosaik com simuladores DSS, CalderaEV e Collector;
3. Mapeamento das cargas de VEs no OpenDSS aos modelos físicos do Caldera;
4. Acoplamento dinâmico de potência ativa P (kW) e reativa Q (kvar);
5. Monitoramento de perfil de recarga dos VEs e perfil de tensão das barras (pu);
6. Consolidação dos resultados em CSV e geração da topologia em JSON.

Uso:
----
    # Execução padrão (1 VE no IEEE 13 barras por 24h, passo de 5 min):
    uv run --no-sync python scenarios/scenario_13bus_ev.py

    # Execução com parâmetros customizados:
    uv run --no-sync python scenarios/scenario_13bus_ev.py --qtd 3 --dias 2 --seed 123
"""

import argparse
from pathlib import Path
from typing import Any

import mosaik
import pandas as pd
from mosaik.util import connect_many_to_one

from simulators.util.ev_creator import alocar_evs

# -----------------------------------------------------------------------------
# 1. Configurações e Caminhos Padrão
# -----------------------------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

DATA_DIR = PROJECT_ROOT / "data" / "13Bus"
CIRCUITO_DSS_PADRAO = DATA_DIR / "IEEE13Nodeckt_w_loadcurve.dss"
DATASET_EVS_PADRAO = (
    PROJECT_ROOT / "data" / "datasets" / "veiculos-eletricos" / "ev_sessions_caldera.csv"
)

OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CSV_RESULTADOS_PADRAO = OUTPUT_DIR / "resultado_scenario_13bus_ev.csv"
JSON_TOPOLOGIA_PADRAO = OUTPUT_DIR / "topologia_13bus_ev.json"

# Simuladores registrados no Mosaik (API v3)
SIM_CONFIG = {
    "DSS": {
        "python": "simulators.opendss.api_opendss:OpenDSSSimulator",
    },
    "CalderaEV": {
        "python": "simulators.ev.caldera_ev_sim:CalderaEVSim",
    },
    "Collector": {
        "python": "simulators.collector.collector:Collector",
    },
}


def executar_cenario_13bus_ev(
    caminho_circuito_dss: Path = CIRCUITO_DSS_PADRAO,
    caminho_ev_sessions: Path = DATASET_EVS_PADRAO,
    arquivo_saida_csv: Path = CSV_RESULTADOS_PADRAO,
    caminho_topologia_json: Path = JSON_TOPOLOGIA_PADRAO,
    qtd_evs: int | None = 1,
    penetracao_pct: float | None = None,
    base_calculo: str = "residencial_bt",
    seed: int = 27,
    passo_minutos: int = 5,
    dias_simulacao: int = 1,
    mostrar_progresso: bool = True,
    barras_especificas: list[str] | None = None,
    barras_excluidas: list[str] | None = None,
) -> pd.DataFrame:
    """Executa o cenário de VEs no alimentador IEEE 13 barras e retorna o DataFrame de resultados."""
    caminho_circuito_dss = Path(caminho_circuito_dss).resolve()
    if not caminho_circuito_dss.exists():
        raise FileNotFoundError(f"Circuito DSS não encontrado: {caminho_circuito_dss}")

    caminho_ev_sessions = Path(caminho_ev_sessions).resolve()
    if not caminho_ev_sessions.exists():
        raise FileNotFoundError(f"Dataset de sessões de VEs não encontrado: {caminho_ev_sessions}")

    step_size = passo_minutos * 60
    n_passos = dias_simulacao * 24 * (60 // passo_minutos)
    end_time = n_passos * step_size

    arquivo_saida_csv = Path(arquivo_saida_csv).resolve()
    arquivo_saida_csv.parent.mkdir(parents=True, exist_ok=True)

    # Arquivo para gravação das cargas de VE no OpenDSS
    arquivo_dss_evs = caminho_circuito_dss.parent / f"{caminho_circuito_dss.stem}_evs.dss"

    print("=" * 75)
    print(" CENÁRIO DE CO-SIMULAÇÃO: VEÍCULOS ELÉTRICOS NO SISTEMA IEEE 13 BARRAS")
    print(f" Circuito DSS  : {caminho_circuito_dss.name}")
    print(
        f" Simulação     : {dias_simulacao} dia(s) | Passo = {passo_minutos} min ({n_passos} passos)"
    )
    print(f" Semente       : {seed}")
    if qtd_evs is not None:
        print(f" Quantidade VE : {qtd_evs}")
    elif penetracao_pct is not None:
        print(f" Penetração    : {penetracao_pct}% (Base: {base_calculo})")
    print(f" Saída CSV     : {arquivo_saida_csv.name}")
    print("=" * 75)

    # 1. Alocação Estocástica dos Veículos Elétricos na Rede
    print("\n[Etapa 1/4] Alocando Veículos Elétricos na rede IEEE 13 barras...")
    if (qtd_evs == 0) or (penetracao_pct == 0.0):
        print("Cenário Caso Base: Sem Veículos Elétricos alocados.")
        arquivo_dss_evs.write_text("! Caso Base sem Veiculos Eletricos\n", encoding="utf-8")
        metrica_info = "Caso Base (0 VEs)"
    else:
        info_aloc = alocar_evs(
            quantidade=qtd_evs,
            penetracao_pct=penetracao_pct,
            base_calculo=base_calculo,
            seed=seed,
            caminho_dss=caminho_circuito_dss,
            output_dss=arquivo_dss_evs,
            ev_sessions_csv=caminho_ev_sessions,
            barras_especificas=barras_especificas,
            barras_excluidas=barras_excluidas,
        )
        metrica_info = info_aloc["metrica"]
        print(f"-> Alocação concluída: {metrica_info}")

    # Garante a inclusão do arquivo de VEs na compilação do OpenDSS
    conteudo_base = caminho_circuito_dss.read_text(encoding="utf-8", errors="ignore")
    if arquivo_dss_evs.name.lower() in conteudo_base.lower() or not arquivo_dss_evs.exists():
        caminho_dss_simulacao = caminho_circuito_dss
    else:
        caminho_dss_simulacao = (
            caminho_circuito_dss.parent / f"{caminho_circuito_dss.stem}_run_ev.dss"
        )
        caminho_dss_simulacao.write_text(
            f"// Runner automatizado com VEs para IEEE 13 Barras\n"
            f"Redirect {caminho_circuito_dss.name}\n"
            f"Redirect {arquivo_dss_evs.name}\n",
            encoding="utf-8",
        )

    # 2. Configuração e Inicialização do Ambiente Mosaik
    print("\n[Etapa 2/4] Inicializando simuladores no Mosaik...")
    with mosaik.World(SIM_CONFIG, mosaik_config={"start_timeout": 60}) as world:
        dss_sim = world.start(
            "DSS",
            topofile=str(caminho_dss_simulacao),
            step_size=step_size,
            output_graph_path=str(caminho_topologia_json) if caminho_topologia_json else None,
        )
        ev_sim = world.start("CalderaEV", step_size=step_size)
        collector = world.start(
            "Collector",
            start_date="2026-01-01 00:00:00",
            output_file=str(arquivo_saida_csv),
            print_results=False,
        )

        grid = dss_sim.Grid()
        monitor = collector.Monitor()

        # 3. Mapeamento e Acoplamento dos VEs ao OpenDSS e ao Monitor
        print("\n[Etapa 3/4] Mapeando e conectando entidades...")
        ev_dss_map = {
            e.eid: e for e in grid.children if e.type == "Load" and "ev_" in e.eid.lower()
        }

        count_evs = 0
        if ev_dss_map and caminho_ev_sessions.exists():
            df_sessions = pd.read_csv(caminho_ev_sessions)
            perfis_disponiveis = set(df_sessions["Profile_Name"].unique())
            perfis_map = {p.lower(): p for p in perfis_disponiveis}

            for eid_dss, ev_dss_obj in ev_dss_map.items():
                nome_raw = eid_dss.split("-", 1)[1] if "-" in eid_dss else eid_dss
                nome_id = nome_raw[3:] if nome_raw.lower().startswith("ev_") else nome_raw

                profile_slug = "_".join(nome_id.split("_")[:-1])
                profile_name = perfis_map.get(profile_slug.lower())

                if not profile_name:
                    print(f"[AVISO] Perfil não localizado no dataset Caldera: {profile_slug}")
                    continue

                # Cria a entidade VE no simulador Caldera
                ev_obj = ev_sim.CalderaEV.create(
                    1,
                    profile_name=profile_name,
                    csv_path=str(caminho_ev_sessions),
                )[0]

                # Acoplamento dinâmico: potência ativa (kW) e reativa indutiva (kvar)
                world.connect(ev_obj, ev_dss_obj, ("P_kw", "P_kw"), ("Q_kvar", "Q_kvar"))

                # Monitoramento dos atributos físicos do VE no Coletor
                world.connect(ev_obj, monitor, "P_kw", "Q_kvar", "fp", "is_charging")
                count_evs += 1

            print(f"-> {count_evs} VEs acoplados com sucesso aos elementos Load do OpenDSS.")
        else:
            print("-> Nenhum VE ativo para acoplamento.")

        # Conecta as barras para monitoramento de tensão por fase (pu)
        barras = [e for e in grid.children if e.type == "Bus"]
        print(f"-> Monitorando tensões pu em {len(barras)} barras da rede.")
        connect_many_to_one(world, barras, monitor, "V1_pu", "V2_pu", "V3_pu")

        # 4. Execução da Co-simulação
        print(f"\n[Etapa 4/4] Executando simulação temporal ({n_passos} passos)...")
        world.run(until=end_time, print_progress=mostrar_progresso)

    print("\n" + "=" * 75)
    print(" CO-SIMULAÇÃO FINALIZADA COM SUCESSO!")
    print(f" Resultados salvos em: {arquivo_saida_csv}")
    if caminho_topologia_json and Path(caminho_topologia_json).exists():
        print(f" Topologia salva em : {caminho_topologia_json}")
    print("=" * 75)

    # 5. Consolidação e Comprovação dos Resultados
    df_resultados = pd.read_csv(arquivo_saida_csv)
    _exibir_relatorio_comprovacao(df_resultados, count_evs, passo_minutos)
    return df_resultados


def _exibir_relatorio_comprovacao(
    df: pd.DataFrame, qtd_evs: int, passo_minutos: int
) -> dict[str, Any]:
    """Exibe no terminal a síntese quantitativa comprovando a operação correta dos VEs e da rede."""
    print("\n" + "-" * 75)
    print(" RELATÓRIO DE COMPROVAÇÃO DA CO-SIMULAÇÃO (IEEE 13 BARRAS + VE)")
    print("-" * 75)

    total_passos = len(df)
    horas_simuladas = (total_passos * passo_minutos) / 60.0
    print(f"• Total de passos registrados  : {total_passos} ({horas_simuladas:.1f} horas)")

    # Métricas de recarga dos Veículos Elétricos
    cols_p_kw = [c for c in df.columns if "P_kw" in c]
    cols_q_kvar = [c for c in df.columns if "Q_kvar" in c]
    cols_charging = [c for c in df.columns if "is_charging" in c]

    if cols_p_kw:
        p_total_serie = df[cols_p_kw].sum(axis=1)
        potencia_pico_ev_kw = float(p_total_serie.max())
        potencia_media_ev_kw = float(p_total_serie.mean())
        # Energia total: integral da potência no tempo (kW * horas_por_passo)
        horas_passo = passo_minutos / 60.0
        energia_total_kwh = float(p_total_serie.sum() * horas_passo)

        print(f"• Veículos Elétricos ativos     : {qtd_evs}")
        print(f"• Potência Máxima Simultânea    : {potencia_pico_ev_kw:.2f} kW")
        print(f"• Potência Média de Carga       : {potencia_media_ev_kw:.2f} kW")
        print(f"• Energia Total Recarregada     : {energia_total_kwh:.2f} kWh")

        if cols_charging:
            passos_com_recarga = int((df[cols_charging].sum(axis=1) > 0).sum())
            pct_tempo_recarga = (passos_com_recarga / total_passos) * 100.0
            print(
                f"• Intervalos com recarga ativa : {passos_com_recarga} de {total_passos} ({pct_tempo_recarga:.1f}%)"
            )
    else:
        print("• Nenhuma coluna de potência de VE identificada.")

    # Métricas de tensão das barras do IEEE 13
    cols_tensao = [c for c in df.columns if c.endswith("_pu")]
    if cols_tensao:
        v_min = float(df[cols_tensao].min().min())
        v_max = float(df[cols_tensao].max().max())
        print(f"• Tensão Mínima no Feeder      : {v_min:.4f} pu")
        print(f"• Tensão Máxima no Feeder      : {v_max:.4f} pu")
        dentro_faixa = (v_min >= 0.88) and (v_max <= 1.10)
        status_tensao = (
            "ADEQUADA (dentro dos limites operacionais)"
            if dentro_faixa
            else "ATENÇÃO (violação detectada)"
        )
        print(f"• Conformidade de Tensão       : {status_tensao}")

    print("-" * 75 + "\n")
    return {
        "passos": total_passos,
        "evs": qtd_evs,
        "cols": len(df.columns),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Co-simulação de Veículos Elétricos no Alimentador IEEE 13 Barras."
    )
    parser.add_argument(
        "--circuito",
        "-c",
        type=str,
        default=str(CIRCUITO_DSS_PADRAO),
        help=f"Caminho do arquivo .dss principal (padrão: {CIRCUITO_DSS_PADRAO.name}).",
    )
    parser.add_argument(
        "--qtd",
        "-q",
        type=int,
        default=1,
        help="Quantidade fixa de VEs a serem alocados (padrão: 1).",
    )
    parser.add_argument(
        "--penetracao",
        "-p",
        type=float,
        default=None,
        help="Taxa de penetração de VEs em %% (calculada sobre base_calculo).",
    )
    parser.add_argument(
        "--base",
        "-b",
        type=str,
        default="residencial_bt",
        choices=["residencial_bt", "barras_bt", "total_barras"],
        help="Base para percentual de penetração (padrão: 'residencial_bt').",
    )
    parser.add_argument(
        "--seed",
        "-s",
        type=int,
        default=27,
        help="Semente pseudoaleatória de alocação (padrão: 27).",
    )
    parser.add_argument(
        "--passo",
        type=int,
        default=5,
        help="Tamanho do passo de simulação em minutos (padrão: 5 min).",
    )
    parser.add_argument(
        "--dias",
        "-d",
        type=int,
        default=1,
        help="Duração da simulação em dias (padrão: 1 dia = 288 passos).",
    )
    parser.add_argument(
        "--saida",
        type=str,
        default=str(CSV_RESULTADOS_PADRAO),
        help="Arquivo CSV para gravação dos resultados.",
    )
    parser.add_argument(
        "--barras-especificas",
        "--barras-alvo",
        nargs="+",
        default=None,
        help="Lista de barras onde os VEs DEVEM ser alocados (whitelist).",
    )
    parser.add_argument(
        "--barras-excluidas",
        "--ignorar-barras",
        nargs="+",
        default=None,
        help="Lista de barras que NÃO DEVEM receber VEs (blacklist).",
    )

    args = parser.parse_args()
    executar_cenario_13bus_ev(
        caminho_circuito_dss=Path(args.circuito),
        arquivo_saida_csv=Path(args.saida),
        qtd_evs=args.qtd if args.penetracao is None else None,
        penetracao_pct=args.penetracao,
        base_calculo=args.base,
        seed=args.seed,
        passo_minutos=args.passo,
        dias_simulacao=args.dias,
        barras_especificas=args.barras_especificas,
        barras_excluidas=args.barras_excluidas,
    )


if __name__ == "__main__":
    main()
