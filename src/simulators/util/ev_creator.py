"""Alocação Estocástica e Modelagem de Veículos Elétricos no OpenDSS
===================================================================

Aloca cargas de Veículos Elétricos (VEs) monofásicos de forma estocástica e
reproduzível na rede de distribuição modelada no OpenDSS.

Metodologia de Alocação:
------------------------
- Adoção Incremental Aninhada (Nested Adoption):
  Baseada na teoria de difusão de inovações (Rogers, 1962; Bass, 1969).
  Para uma dada semente pseudoaleatória, a ordenação de adoção é gerada uma única vez;
  cenários de penetração crescente (ex: 10%, 20%, 30%) expandem a base de adotantes
  preservando estritamente os consumidores alocados nos níveis anteriores.
- Mapeamento elétrico:
  Identifica unidades consumidoras elegíveis (cargas BT residenciais, V_base <= 1,0 kV),
  atribuindo o VE a uma das fases existentes da unidade com conexão monofásica
  fase-neutro em 220 V (potências nominais de 3,6 kW ou 7,2 kW).
- Suporte a filtros de barras prioritárias (whitelist) ou bloqueadas (blacklist).
"""

import argparse
import logging
import os
import random
from pathlib import Path
from typing import Any

import pandas as pd
import py_dss_interface

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s", datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

# --- Detecção Automática da Raiz do Projeto ---
CURRENT_FILE = Path(__file__).resolve()


def _detectar_raiz_projeto() -> Path:
    """Localiza o diretório raiz do projeto navegando pelos diretórios pai."""
    curr = CURRENT_FILE.parent
    while curr.parent != curr:
        if (curr / "pyproject.toml").exists() or (curr / "data").exists():
            return curr
        curr = curr.parent
    return CURRENT_FILE.parents[2]


PROJECT_ROOT = _detectar_raiz_projeto()
DEFAULT_EV_SESSIONS = (
    PROJECT_ROOT / "data" / "datasets" / "veiculos-eletricos" / "ev_sessions_caldera.csv"
)
DEFAULT_EV_CSV = (
    PROJECT_ROOT / "data" / "datasets" / "veiculos-eletricos" / "ev_loadshapes_normalized.csv"
)


def _normalizar_lista_barras(lista_ou_str: list[str] | set[str] | str | None) -> set[str] | None:
    """Converte listas, tuplas, conjuntos ou strings de nomes de barras em conjunto canônico (minúsculo e sem fases)."""
    if not lista_ou_str:
        return None
    if isinstance(lista_ou_str, str):
        tokens = [
            t.strip().lower().split(".")[0]
            for t in lista_ou_str.replace(",", " ").split()
            if t.strip()
        ]
    elif isinstance(lista_ou_str, (list, tuple, set)):
        tokens = [str(b).strip().lower().split(".")[0] for b in lista_ou_str if str(b).strip()]
    else:
        tokens = [str(lista_ou_str).strip().lower().split(".")[0]]
    return set(tokens)


def mapear_topologia_cargas(caminho_dss: Path, output_dss_path: Path) -> dict[str, Any]:
    """Compila o circuito no OpenDSS e mapeia as barras e cargas elegíveis da rede.

    Aplica estratégia hierárquica de identificação:
    1. Cargas BT com prefixo residencial ('bt_');
    2. Cargas gerais de Baixa Tensão (kv_base <= 1.0 kV);
    3. Cargas gerais do alimentador (caso a rede seja puramente MT).

    Cargas multifásicas ou com medidores múltiplos (_M1/_M2) são agrupadas por
    unidade consumidora única (uc_id).
    """
    original_cwd = os.getcwd()
    try:
        dss = py_dss_interface.DSS()
        logger.info(f"Compilando circuito para mapeamento de cargas: {caminho_dss.name}")

        # Garante que o arquivo de EVs exista (mesmo vazio) para evitar erro de compilação
        output_dss_path.parent.mkdir(parents=True, exist_ok=True)
        if not output_dss_path.exists():
            with open(output_dss_path, "w", encoding="utf-8") as f:
                f.write("! Arquivo temporario vazio\n")

        dss.text("Clear")
        dss.text(f"set datapath={caminho_dss.parent}")
        dss.text(f"Compile [{caminho_dss}]")

        todas_barras = dss.circuit.buses_names
        total_barras_feeder = dss.circuit.num_buses or len(todas_barras)

        todas_cargas = []
        dss.loads.first()
        while True:
            nome_carga = dss.loads.name
            if not nome_carga:
                break

            dss.circuit.set_active_element(f"Load.{nome_carga}")
            bus_str = dss.cktelement.bus_names[0]
            base_bus = bus_str.split(".")[0]
            nos = bus_str.split(".")[1:]
            fases = [n for n in nos if n in ["1", "2", "3"]]
            if not fases:
                fases = ["1", "2", "3"]

            dss.circuit.set_active_bus(base_bus)
            kv_base = dss.bus.kv_base
            dss.loads.name = nome_carga
            kv_load = dss.loads.kv

            todas_cargas.append(
                {
                    "nome": nome_carga,
                    "bus": base_bus,
                    "fases": fases,
                    "kv_base": kv_base,
                    "kv_load": kv_load,
                }
            )

            if not dss.loads.next():
                break
    finally:
        os.chdir(original_cwd)

    if not todas_cargas:
        raise RuntimeError(f"Nenhuma carga (Load) encontrada no circuito OpenDSS: {caminho_dss}")

    # Seleção hierárquica das cargas residenciais BT:
    cargas_bt_prefix = [
        c for c in todas_cargas if c["nome"].lower().startswith("bt_") and c["kv_base"] <= 1.0
    ]
    cargas_bt_geral = [c for c in todas_cargas if c["kv_base"] <= 1.0]

    if cargas_bt_prefix:
        cargas_selecionadas = cargas_bt_prefix
        tipo_base = "domicílios residenciais BT (prefixo bt_)"
    elif cargas_bt_geral:
        cargas_selecionadas = cargas_bt_geral
        tipo_base = "cargas de Baixa Tensão (kv_base <= 1 kV)"
    else:
        cargas_selecionadas = todas_cargas
        tipo_base = "cargas do alimentador (rede MT)"

    consumidores_alvo: dict[str, dict[str, Any]] = {}
    for c in cargas_selecionadas:
        nome_carga = c["nome"]
        uc_id = nome_carga.rsplit("_", 1)[0]
        if uc_id not in consumidores_alvo:
            if c["kv_base"] <= 1.0:
                kv_ev = 0.220  # 220V padrão fase-neutro
            else:
                kv_ev = c["kv_load"] if c["kv_load"] > 0 else (c["kv_base"] / 1.732)
            consumidores_alvo[uc_id] = {
                "uc_id": uc_id,
                "bus": c["bus"],
                "phases": c["fases"],
                "kv": kv_ev,
            }

    barras_unicas = sorted(list({c["bus"] for c in consumidores_alvo.values()}))

    logger.info(
        f"Mapeamento concluído ({tipo_base}): {len(consumidores_alvo)} pontos de consumo identificados em "
        f"{len(barras_unicas)} barras (Total da rede: {total_barras_feeder} barras)."
    )

    return {
        "consumidores": consumidores_alvo,
        "barras_unicas": barras_unicas,
        "total_barras_feeder": total_barras_feeder,
        "tipo_base": tipo_base,
    }


def alocar_evs(
    quantidade: int | None = None,
    penetracao_pct: float | None = None,
    base_calculo: str = "residencial_bt",
    seed: int = 42,
    caminho_dss: Path | None = None,
    output_dss: Path | None = None,
    ev_sessions_csv: Path | None = None,
    barras_especificas: list[str] | set[str] | str | None = None,
    barras_excluidas: list[str] | set[str] | str | None = None,
) -> dict[str, Any]:
    """Aloca Veículos Elétricos monofásicos de forma estocástica e reproduzível na rede.

    Parâmetros:
    -----------
    quantidade: int, opcional
        Número absoluto direto de VEs a serem alocados (ex: 10, 50, 100).
        Se informado, sobrepõe o cálculo percentual de penetração.
    penetracao_pct: float, opcional
        Taxa de penetração em porcentagem (ex: 5.0 para 5%, 20.0 para 20%).
    base_calculo: str, padrão "residencial_bt"
        Define a base para cálculo quando penetracao_pct for utilizado:
        - "residencial_bt": % dos domicílios / cargas elegíveis.
        - "barras_bt": % das barras elegíveis.
        - "total_barras": % do total de barras do alimentador.
    seed: int, padrão 42
        Semente pseudoaleatória para reprodutibilidade estrita.
    caminho_dss: Path, opcional
        Caminho do arquivo principal do circuito DSS.
    output_dss: Path, opcional
        Caminho onde será salvo o arquivo de VEs (.dss).
    ev_sessions_csv: Path, opcional
        Caminho do CSV de sessões de recarga Caldera.
    barras_especificas: list, set ou str, opcional
        Lista de barras onde os VEs DEVEM ser alocados (whitelist).
        Pode ser uma lista de strings ou texto separado por vírgulas.
    barras_excluidas: list, set ou str, opcional
        Lista de barras que NÃO DEVEM receber VEs (blacklist).
        Pode ser uma lista de strings ou texto separado por vírgulas.

    Retorno:
    --------
    dict com informações detalhadas da alocação realizada.
    """
    if caminho_dss is None:
        raise ValueError("O parâmetro 'caminho_dss' com o caminho do circuito DSS é obrigatório.")

    caminho_dss = Path(caminho_dss).resolve()
    output_dss = (
        Path(output_dss).resolve()
        if output_dss
        else caminho_dss.parent / f"{caminho_dss.stem}_evs.dss"
    )
    ev_sessions_csv = Path(ev_sessions_csv).resolve() if ev_sessions_csv else DEFAULT_EV_SESSIONS

    random.seed(seed)

    dados_topologia = mapear_topologia_cargas(caminho_dss, output_dss)
    consumidores = dados_topologia["consumidores"]
    total_barras_feeder = dados_topologia["total_barras_feeder"]

    # 1. Aplicação dos Filtros de Barras Específicas e Barras Excluídas
    set_especificas = _normalizar_lista_barras(barras_especificas)
    set_excluidas = _normalizar_lista_barras(barras_excluidas)

    candidatos_consumidores = {}
    for uc_id, c in consumidores.items():
        bus_norm = str(c["bus"]).lower().split(".")[0]

        # Bloqueia barras excluídas
        if set_excluidas and bus_norm in set_excluidas:
            continue

        # Restringe a barras específicas se fornecidas
        if set_especificas is not None and bus_norm not in set_especificas:
            continue

        candidatos_consumidores[uc_id] = c

    # Se barras_especificas continha barras válidas sem cargas existentes, adiciona pontos de conexão
    if set_especificas:
        barras_com_carga = {
            str(c["bus"]).lower().split(".")[0] for c in candidatos_consumidores.values()
        }
        barras_sem_carga = set_especificas - barras_com_carga
        if set_excluidas:
            barras_sem_carga = barras_sem_carga - set_excluidas

        for b_nome in sorted(list(barras_sem_carga)):
            candidatos_consumidores[f"PONTO_{b_nome}"] = {
                "uc_id": f"PONTO_{b_nome}",
                "bus": b_nome,
                "phases": ["1", "2", "3"],
                "kv": 0.220,
            }

    if not candidatos_consumidores:
        raise ValueError(
            "Nenhum ponto de conexão elegível encontrado na rede após aplicar os filtros: "
            f"barras_especificas ({len(set_especificas) if set_especificas else 'N/A'}) e "
            f"barras_excluidas ({len(set_excluidas) if set_excluidas else 'N/A'})."
        )

    total_consumidores_elegiveis = len(candidatos_consumidores)
    barras_elegiveis_unicas = sorted(
        list({str(c["bus"]).lower().split(".")[0] for c in candidatos_consumidores.values()})
    )
    total_barras_elegiveis = len(barras_elegiveis_unicas)

    # 2. Determinação da Quantidade de VEs
    if quantidade is not None:
        qtd_evs = int(quantidade)
        if qtd_evs < 0:
            raise ValueError("A quantidade de VEs não pode ser negativa.")
        metrica_str = f"Quantidade fixa direta ({qtd_evs} VEs)"
    elif penetracao_pct is not None:
        pct = float(penetracao_pct)
        if pct < 0:
            raise ValueError("A taxa de penetração percentual não pode ser negativa.")

        base_norm = base_calculo.lower().strip()
        if base_norm in ["residencial_bt", "domiciliar", "domicilio", "domicilios", "residencial"]:
            qtd_evs = max(1, round((pct / 100.0) * total_consumidores_elegiveis)) if pct > 0 else 0
            metrica_str = f"{pct:.1f}% de Adoção ({qtd_evs} VEs sobre {total_consumidores_elegiveis} pontos elegíveis)"
        elif base_norm in ["barras_bt", "barra_bt", "bus_bt"]:
            qtd_evs = max(1, round((pct / 100.0) * total_barras_elegiveis)) if pct > 0 else 0
            metrica_str = f"{pct:.1f}% das Barras Elegíveis ({qtd_evs} VEs sobre {total_barras_elegiveis} barras)"
        elif base_norm in ["total_barras", "barras_totais", "feeder_buses"]:
            qtd_evs = max(1, round((pct / 100.0) * total_barras_feeder)) if pct > 0 else 0
            metrica_str = f"{pct:.1f}% do Total de Barras ({qtd_evs} VEs sobre {total_barras_feeder} barras totais)"
        else:
            raise ValueError(
                f"Base de cálculo '{base_calculo}' não suportada. "
                f"Opções válidas: 'residencial_bt', 'barras_bt', 'total_barras'."
            )
    elif set_especificas is not None:
        qtd_evs = total_barras_elegiveis
        metrica_str = (
            f"1 VE por barra específica ({qtd_evs} VEs em {total_barras_elegiveis} barras)"
        )
    else:
        qtd_evs = 50
        metrica_str = f"Padrão fixo ({qtd_evs} VEs)"

    if set_especificas:
        metrica_str += f" [Restrito a {len(set_especificas)} barras alvo]"
    if set_excluidas:
        metrica_str += f" [{len(set_excluidas)} barras excluídas]"

    # 3. Caso Base sem VEs
    if qtd_evs == 0:
        with open(output_dss, "w", encoding="utf-8") as f:
            f.write("! Caso Base sem Veiculos Eletricos\n")
        logger.info(f"Caso Base: Nenhum VE alocado ({output_dss})")
        return {
            "output_dss": str(output_dss),
            "qtd_evs": 0,
            "seed": seed,
            "metrica": "Caso Base (0 VEs)",
            "total_pontos": total_consumidores_elegiveis,
            "total_barras": total_barras_elegiveis,
            "comandos_dss": [],
        }

    # 4. Carregamento dos Perfis Disponíveis
    if ev_sessions_csv.exists():
        logger.info(f"Lendo perfis de VEs do dataset Caldera: {ev_sessions_csv.name}")
        df_sessions = pd.read_csv(ev_sessions_csv)
        curvas_disponiveis = sorted(df_sessions["Profile_Name"].unique())
    elif DEFAULT_EV_CSV.exists():
        logger.info(f"Lendo perfis de VEs do dataset CSV padrão: {DEFAULT_EV_CSV.name}")
        df_evs = pd.read_csv(DEFAULT_EV_CSV)
        curvas_disponiveis = [col for col in df_evs.columns if col.lower() not in ["date", "time"]]
    else:
        raise FileNotFoundError(
            f"Arquivo de perfis de VEs não encontrado em: {ev_sessions_csv} ou {DEFAULT_EV_CSV}"
        )

    # 5. Seleção Estocástica Incremental Aninhada (Nested Adoption)
    # A ordenação de consumidores elegíveis é determinada uma única vez para a semente informada.
    # Cenários com maior penetração (ex: 20%) contêm estritamente todos os veículos alocados
    # nos cenários de menor penetração (ex: 10%), refletindo a dinâmica cumulativa de adoção.
    rng = random.Random(seed)
    lista_candidatos = sorted(
        list(candidatos_consumidores.values()),
        key=lambda c: (str(c.get("bus", "")), str(c.get("uc_id", ""))),
    )
    rng.shuffle(lista_candidatos)

    fila_adocao_ves = []
    for idx, local in enumerate(lista_candidatos, start=1):
        curva_sorteada = rng.choice(curvas_disponiveis)
        no_fase = rng.choice(local["phases"])
        fila_adocao_ves.append(
            {
                "idx": idx,
                "local": local,
                "curva": curva_sorteada,
                "fase": no_fase,
            }
        )

    # Alocação cumulativa: caso a quantidade de VEs ultrapasse o total de consumidores,
    # permite múltiplos veículos por unidade consumidora/barra mantendo a ordenação.
    veiculos_alocados = []
    contador_global = 1
    while len(veiculos_alocados) < qtd_evs:
        restantes = qtd_evs - len(veiculos_alocados)
        fatia = fila_adocao_ves[:restantes]
        for item in fatia:
            item_copia = dict(item)
            item_copia["global_id"] = contador_global
            contador_global += 1
            veiculos_alocados.append(item_copia)

    logger.info(
        f"Alocando {qtd_evs} VEs monofásicos (Lógica Incremental Aninhada - {metrica_str})..."
    )

    ev_commands: list[str] = []
    for item in veiculos_alocados:
        g_id = item["global_id"]
        local = item["local"]
        curva_sorteada = item["curva"]
        no_fase = item["fase"]

        bus_monofasico = f"{local['bus']}.{no_fase}.4"
        potencia = 3.6 if ("3.6" in curva_sorteada or "3p6" in curva_sorteada) else 7.2
        kv_monofasico = local["kv"]

        nome_id = f"{curva_sorteada}_{g_id}"
        cmd = (
            f"New Load.EV_{nome_id} Bus1={bus_monofasico} Phases=1 Conn=Wye "
            f"kV={kv_monofasico:.3f} kW={potencia} pf=1.0 status=variable"
        )
        ev_commands.append(cmd)

    # 6. Gravação do Arquivo DSS
    with open(output_dss, "w", encoding="utf-8") as f:
        f.write("! ======================================================================\n")
        f.write(f"! ARQUIVO DE VEÍCULOS ELÉTRICOS GERADO AUTOMATICAMENTE ({qtd_evs} VEs)\n")
        f.write(f"! Circuito: {caminho_dss.name} | Semente: {seed} | Métrica: {metrica_str}\n")
        if set_especificas:
            f.write(f"! Barras Alvo Especificadas: {sorted(list(set_especificas))}\n")
        if set_excluidas:
            f.write(f"! Barras Excluídas (Bloqueadas): {sorted(list(set_excluidas))}\n")
        f.write("! ======================================================================\n\n")
        for cmd in ev_commands:
            f.write(f"{cmd}\n")

    logger.info(f"Arquivo DSS de VEs gravado com sucesso: {output_dss} ({len(ev_commands)} cargas)")

    return {
        "output_dss": str(output_dss),
        "qtd_evs": qtd_evs,
        "seed": seed,
        "metrica": metrica_str,
        "total_pontos": total_consumidores_elegiveis,
        "total_barras": total_barras_elegiveis,
        "barras_alocadas": sorted(
            list({str(item["local"]["bus"]).lower().split(".")[0] for item in veiculos_alocados})
        ),
        "comandos_dss": ev_commands,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Alocador Universal de Veículos Elétricos em Redes OpenDSS."
    )
    parser.add_argument(
        "--circuito",
        "-c",
        type=str,
        required=True,
        help="Caminho do arquivo principal DSS da rede.",
    )
    parser.add_argument(
        "--output", "-o", type=str, default=None, help="Caminho onde salvar o arquivo DSS de VEs."
    )
    parser.add_argument(
        "--qtd",
        "-q",
        "--quantidade",
        type=int,
        default=None,
        help="Quantidade direta/exata de VEs a alocar.",
    )
    parser.add_argument(
        "--penetracao",
        "-p",
        type=float,
        default=None,
        help="Taxa de penetração em porcentagem (ex: 20.0).",
    )
    parser.add_argument(
        "--base",
        "-b",
        type=str,
        default="residencial_bt",
        help="Base de cálculo: residencial_bt, barras_bt, total_barras.",
    )
    parser.add_argument(
        "--seed", "-s", type=int, default=42, help="Semente pseudoaleatória (default: 42)."
    )
    parser.add_argument(
        "--barras-especificas",
        "--barras-alvo",
        "--barras",
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
    alocar_evs(
        quantidade=args.qtd,
        penetracao_pct=args.penetracao,
        base_calculo=args.base,
        seed=args.seed,
        caminho_dss=Path(args.circuito),
        output_dss=Path(args.output) if args.output else None,
        barras_especificas=args.barras_especificas,
        barras_excluidas=args.barras_excluidas,
    )
