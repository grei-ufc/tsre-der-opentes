"""Shim de compatibilidade — o adaptador de inversor agora é único.

``simulators.inverter.inverter_simulator:InverterSim`` continua resolvendo, mas
aponta para :class:`~.smart_inverter_simulator.SmartInverterSim`, que atende
tanto o inversor comum (sem funções de rede) quanto o inteligente.

Os parâmetros dos cenários anteriores — ``kVA``, ``priority``, ``eff_curve_x``,
``eff_curve_y``, ``pct_cutin``, ``pct_cutout`` — continuam aceitos. Sem
``ctrl_config``, nenhuma função do OpenDER é ativada e o inversor segue o
``Q_des`` recebido, exatamente como antes.

Para código novo, importe de :mod:`~.smart_inverter_simulator`.
"""

from .smart_inverter_simulator import META, InverterSim, SmartInverterSim, main

__all__ = ["META", "InverterSim", "SmartInverterSim", "main"]


if __name__ == "__main__":
    main()
