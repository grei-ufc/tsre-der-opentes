"""
Funções helper reutilizáveis para normalização de dados trifásicos
retornados pelo OpenDSS.
"""
from typing import Any, Dict, List, Tuple, Union


def to_3phase(value: Union[float, Tuple, List, None]) -> List[float]:
    """
    Normaliza qualquer retorno do OpenDSS (escalar, tupla, lista)
    para uma lista de 3 elementos, preenchendo com 0.0 quando necessário.
    """
    if value is None:
        return [0.0, 0.0, 0.0]
    if isinstance(value, (list, tuple)):
        result = list(value)
    else:
        result = [value]
    while len(result) < 3:
        result.append(0.0)
    return result


def extract_3phase_pq(
    dss_wrapper,
    name: str,
    element: str,
    attrs: Dict[str, Any],
    sign: int = -1,
    line_bus: int = 1,
) -> Dict[str, float]:
    """
    Extrai potências e correntes trifásicas de um elemento e mapeia
    para os atributos do Mosaik (Storage, PVSystem, etc.).

    Atributos suportados: P1/P2/P3, Q1/Q2/Q3, I1_A/I2_A/I3_A,
    e totais P_act/Q_act (ou P_meas/Q_meas) quando presentes em attrs.

    Args:
        dss_wrapper: Instância de OpenDSS wrapper.
        name: Nome do elemento.
        element: Classe do elemento ('Storage', 'PVSystem', etc.).
        attrs: Dicionário de atributos solicitados pelo Mosaik.
        sign: Sinal de inversão (-1 para injeção, 1 para consumo).
        line_bus: Terminal para elementos de linha (1 ou 2).

    Returns:
        Dict com valores dos atributos solicitados.
    """
    data: Dict[str, float] = {}

    # Potências por fase
    p_raw, q_raw = dss_wrapper.get_power(
        name=name, element=element, total=False, line_bus=line_bus,
    )
    p_list = to_3phase(p_raw)
    q_list = to_3phase(q_raw)

    # Correntes por fase
    curr_mag, _ = dss_wrapper.get_current(
        name, element=element, polar=True, mag_only=False, line_bus=line_bus,
    )
    i_mags = to_3phase(curr_mag)

    p_map = {'P1': 0, 'P2': 1, 'P3': 2}
    q_map = {'Q1': 0, 'Q2': 1, 'Q3': 2}
    i_map = {'I1_A': 0, 'I2_A': 1, 'I3_A': 2}

    for attr in attrs:
        if attr in p_map:
            data[attr] = sign * p_list[p_map[attr]]
        elif attr in q_map:
            data[attr] = sign * q_list[q_map[attr]]
        elif attr in i_map:
            data[attr] = i_mags[i_map[attr]]
        elif attr in ('P_act', 'P_meas'):
            data[attr] = sign * sum(p_list)
        elif attr in ('Q_act', 'Q_meas'):
            data[attr] = sign * sum(q_list)

    return data
