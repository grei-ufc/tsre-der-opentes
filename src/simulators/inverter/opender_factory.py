"""Construção de objetos OpenDER a partir de uma :class:`~.config.ControlConfig`.

Este é o **único** lugar do projeto que fala com o ``DERCommonFileFormat``. A
regra que ele impõe existe por causa de um modo de falha real e silencioso:

    O setter de ``NP_VA_MAX`` reexecuta ``initialize_NP_Q_CAPABILTY_BY_P_CURVE()``
    usando o ``NP_Q_MAX_INJ`` corrente. Ajustar a potência de um DER já
    construído — sem reajustar o par de capacidade reativa — deixa a curva em
    ``44 kvar / NP_VA_MAX``, e o volt-var passa a entregar uma fração da
    potência reativa pretendida sem nenhum erro.

Por isso o arquivo de parâmetros é montado **completo, de uma vez**, e passado
ao construtor do DER. Nada é mutado depois, e :func:`build_der` confere a curva
de capacidade resultante antes de devolver o objeto.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from .config import ControlConfig, InverterUnit, PhaseMode

if TYPE_CHECKING:  # pragma: no cover - apenas para tipagem
    from opender import DER_PV

logger = logging.getLogger(__name__)

# Tolerância da conferência da curva de capacidade reativa (em pu).
_Q_CAPABILITY_TOL = 1e-6

# Avisos do OpenDER já reportados, para não repetir por inversor num
# alimentador com centenas deles.
_reported_warnings: set[str] = set()

# Passo global corrente, para detectar simuladores em desacordo.
_time_step: float | None = None


__all__ = [
    "OpenDERSetupError",
    "build_der",
    "build_der_file",
    "current_time_step",
    "reset_time_step",
    "set_time_step",
]


class OpenDERSetupError(RuntimeError):
    """O objeto OpenDER não ficou consistente com a configuração pedida."""


# ----------------------------------------------------------------------
# Passo de simulação (atributo de classe, global ao processo)
# ----------------------------------------------------------------------


def set_time_step(t_s: float) -> None:
    """Define ``DER.t_s``, o passo de simulação de **todos** os DERs do processo.

    ``t_s`` é atributo de classe no OpenDER, não de instância: o último valor
    escrito vale para todo objeto já criado. Dois simuladores de inversor com
    passos diferentes no mesmo processo silenciosamente compartilhariam o
    último, então o desacordo é reportado.

    Args:
        t_s: Passo em segundos.

    Raises:
        ValueError: Se ``t_s`` não for positivo.
    """
    global _time_step

    if t_s <= 0:
        raise ValueError(f"passo de simulação deve ser > 0; recebido {t_s}")

    from opender import DER

    if _time_step is not None and abs(_time_step - t_s) > 1e-9:
        logger.warning(
            "[OpenTES][OpenDER] DER.t_s ja estava em %.6gs e foi redefinido para %.6gs. "
            "t_s e um atributo de CLASSE: o novo valor passa a valer para todos os DERs "
            "ja criados neste processo, alterando OLRT, rampa de entrada em servico e "
            "temporizadores de trip retroativamente.",
            _time_step,
            t_s,
        )

    DER.t_s = t_s
    _time_step = t_s


def current_time_step() -> float | None:
    """Passo atualmente configurado, ou ``None`` se nunca definido aqui."""
    return _time_step


def reset_time_step() -> None:
    """Esquece o passo registrado. Existe para isolar testes."""
    global _time_step
    _time_step = None
    _reported_warnings.clear()


# ----------------------------------------------------------------------
# Captura dos avisos do OpenDER
# ----------------------------------------------------------------------


class _Collector(logging.Filter):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            self.messages.append(record.getMessage())
            return False  # engolido aqui; reemitido com o nome da unidade
        return True


@contextmanager
def _collect_opender_warnings():
    """Captura os ``logging.warning`` que o OpenDER emite na raiz.

    O OpenDER valida os ajustes nos *setters* e apenas avisa. Sem contexto, o
    aviso não diz de qual inversor veio; com centenas deles, vira ruído. Aqui os
    avisos são coletados para serem reemitidos uma única vez, com a unidade.
    """
    collector = _Collector()
    root = logging.getLogger()
    root.addFilter(collector)
    try:
        yield collector
    finally:
        root.removeFilter(collector)


# ----------------------------------------------------------------------
# Construção
# ----------------------------------------------------------------------


def _nameplate_params(unit: InverterUnit, ctrl: ControlConfig) -> dict[str, Any]:
    """Parâmetros de placa, na ordem em que precisam ser escritos.

    A ordem não é cosmética. Três setters — ``NP_VA_MAX``, ``NP_Q_MAX_INJ`` e
    ``NP_Q_MAX_ABS`` — reexecutam a inicialização da curva de capacidade
    reativa, e ``NP_Q_CAPABILITY_LOW_P`` também. Escrever a potência aparente
    primeiro e a capacidade reativa depois garante que a curva final saia dos
    três valores já coerentes entre si.

    ``NP_V_DC`` precede ``NP_AC_V_NOM`` porque o setter da tensão AC corrige a
    tensão DC — e avisa — sempre que ela ficar abaixo do pico linha-linha.
    """
    if unit.kv is None:
        raise OpenDERSetupError(
            f"Unidade {unit.name!r}: 'kv' é obrigatório quando alguma função do OpenDER "
            "está ativa — é a base de v_pu para as curvas volt-var e volt-watt. "
            "Use a tensão linha-linha se trifásica, linha-neutro se monofásica."
        )

    va_max = unit.kva * 1000.0
    p_max = unit.kw_rating * 1000.0
    v_nom = unit.kv * 1000.0

    return {
        "NP_TYPE": "PV",
        "NP_PHASE": unit.phase_mode.value,
        "NP_V_DC": v_nom * 1.5,
        "NP_AC_V_NOM": v_nom,
        "NP_VA_MAX": va_max,
        "NP_P_MAX": p_max,
        # Um sistema fotovoltaico não carrega. Os dois campos ficam iguais
        # porque a verificação de placa do OpenDER avisa quando a potência
        # ativa de carga é menor que a aparente — o que seria o caso normal.
        "NP_P_MAX_CHARGE": 0.0,
        "NP_APPARENT_POWER_CHARGE_MAX": 0.0,
        "NP_Q_MAX_INJ": unit.q_inj_pu * va_max,
        "NP_Q_MAX_ABS": unit.q_abs_pu * va_max,
        "NP_Q_CAPABILITY_LOW_P": ctrl.q_capability_low_p,
    }


def der_params(unit: InverterUnit, ctrl: ControlConfig) -> dict[str, Any]:
    """Dicionário completo de parâmetros do ``DERCommonFileFormat``.

    Exposto separadamente de :func:`build_der_file` para que os testes possam
    inspecionar a tradução sem instanciar um DER.
    """
    params = _nameplate_params(unit, ctrl)
    params.update(ctrl.as_der_params())
    return params


def build_der_file(unit: InverterUnit, ctrl: ControlConfig) -> Any:
    """Monta um ``DERCommonFileFormat`` completo para *unit*.

    Args:
        unit: Unidade física a representar.
        ctrl: Funções de controle a habilitar.

    Returns:
        Um ``DERCommonFileFormat`` pronto para o construtor do DER.
    """
    from opender import DERCommonFileFormat

    params = der_params(unit, ctrl)

    with _collect_opender_warnings() as collected:
        der_file = DERCommonFileFormat(**params)

    for message in collected.messages:
        if message in _reported_warnings:
            continue
        _reported_warnings.add(message)
        logger.warning("[OpenTES][OpenDER] %s (unidade %r)", message, unit.name)

    return der_file


def _check_q_capability(der_file: Any, unit: InverterUnit) -> None:
    """Confere que a curva de capacidade reativa reflete o kVA da unidade.

    Guarda de regressão para o modo de falha descrito no topo do módulo. A
    curva é interpolada em pu de ``NP_VA_MAX``; em ``P = 1 pu`` ela deve valer
    exatamente ``q_inj_pu`` / ``q_abs_pu``.
    """
    curve = der_file.NP_Q_CAPABILITY_BY_P_CURVE
    checks = (
        ("injeção", curve["Q_MAX_INJ_PU"][-1], unit.q_inj_pu),
        ("absorção", curve["Q_MAX_ABS_PU"][-1], unit.q_abs_pu),
    )
    for label, actual, expected in checks:
        if abs(actual - expected) > _Q_CAPABILITY_TOL:
            raise OpenDERSetupError(
                f"Unidade {unit.name!r}: capacidade de {label} de reativo ficou em "
                f"{actual:.4f} pu, esperado {expected:.4f} pu. Isso indica que "
                f"NP_VA_MAX ({der_file.NP_VA_MAX:.0f} VA) foi ajustado sem o par "
                f"NP_Q_MAX_INJ/NP_Q_MAX_ABS correspondente."
            )


def build_der(unit: InverterUnit, ctrl: ControlConfig) -> DER_PV:
    """Cria o ``DER_PV`` de uma unidade, com a configuração já aplicada.

    Args:
        unit: Unidade física a representar.
        ctrl: Funções de controle a habilitar.

    Returns:
        Um ``DER_PV`` pronto para receber ``update_der_input`` e ``run``.

    Raises:
        OpenDERSetupError: Se a capacidade reativa resultante não corresponder
            à potência da unidade.
    """
    from opender import DER_PV

    der_file = build_der_file(unit, ctrl)
    _check_q_capability(der_file, unit)

    # O construtor do DER reexecuta `nameplate_value_validity_check`, que
    # também avisa pela raiz; sem a captura, cada inversor repetiria o aviso.
    with _collect_opender_warnings() as collected:
        der = DER_PV(der_file)

    for message in collected.messages:
        if message in _reported_warnings:
            continue
        _reported_warnings.add(message)
        logger.warning("[OpenTES][OpenDER] %s (unidade %r)", message, unit.name)

    der.name = unit.name
    return der


def voltage_for(unit: InverterUnit, v_meas: list[float | None]) -> float | list[float]:
    """Seleciona a tensão que a unidade enxerga, a partir das tensões da barra.

    Args:
        unit: Unidade cuja conexão determina a seleção.
        v_meas: Tensões de fase da barra em pu, indexadas por nó (1..3).
            ``None`` marca uma fase não conectada.

    Returns:
        Escalar para unidade monofásica, lista de três para trifásica.

    Raises:
        OpenDERSetupError: Se a tensão de um nó ocupado pela unidade estiver
            ausente. Substituir por 1.0 em silêncio esconderia um erro de
            ligação do cenário exatamente na grandeza que comanda o controle.
    """
    missing = [n for n in unit.nodes if v_meas[n - 1] is None]
    if missing:
        raise OpenDERSetupError(
            f"Unidade {unit.name!r}: sem tensão medida para o(s) nó(s) {missing}. "
            f"Conecte V_meas_{missing[0]} a partir da barra no cenário."
        )

    if unit.phase_mode is PhaseMode.SINGLE:
        return float(v_meas[unit.node - 1])  # type: ignore[index,arg-type]
    return [float(v_meas[i]) for i in range(3)]  # type: ignore[arg-type]
