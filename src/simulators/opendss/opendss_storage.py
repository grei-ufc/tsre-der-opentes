"""
Operacoes de Storage no OpenDSS.

Funcoes standalone que recebem a instancia ``dss`` (py_dss_interface.DSS)
e encapsulam leitura de parametros estaticos de baterias.
"""
from typing import Dict


def get_all_storages_info(dss) -> Dict[str, dict]:
    """Retorna dados estaticos de todos os elementos Storage.

    Args:
        dss: Instancia py_dss_interface.DSS ativa.

    Returns:
        Dict mapeando nome_do_Storage -> dict com parametros.
    """
    storage_infos: Dict[str, dict] = {}

    dss.circuit.set_active_class("Storage")
    if dss.active_class.count == 0:
        return storage_infos

    names = dss.active_class.names
    if not names or names[0] is None or str(names[0]).lower() == "none":
        return storage_infos

    for full_name in names:
        name = full_name.split(".")[-1] if "." in full_name else full_name

        kw_rated = float(dss.text(f"? Storage.{name}.kWrated"))
        kwh_rated = float(dss.text(f"? Storage.{name}.kWhrated"))
        kwh_stored = float(dss.text(f"? Storage.{name}.kWhstored"))
        pct_reserve = float(dss.text(f"? Storage.{name}.%reserve"))
        eff_charge = float(dss.text(f"? Storage.{name}.%EffCharge"))
        eff_discharge = float(dss.text(f"? Storage.{name}.%EffDischarge"))
        pct_idling = float(dss.text(f"? Storage.{name}.%IdlingkW"))
        daily = dss.text(f"? Storage.{name}.daily")
        charge_trigger = float(dss.text(f"? Storage.{name}.chargeTrigger"))
        discharge_trigger = float(dss.text(f"? Storage.{name}.dischargeTrigger"))

        storage_infos[name] = {
            "name": name,
            "kw_rated": kw_rated,
            "kwh_rated": kwh_rated,
            "kwh_stored": kwh_stored,
            "pct_reserve": pct_reserve,
            "eff_charge": eff_charge,
            "eff_discharge": eff_discharge,
            "pct_idling": pct_idling,
            "daily": daily,
            "charge_trigger": charge_trigger,
            "discharge_trigger": discharge_trigger,
        }

    return storage_infos
