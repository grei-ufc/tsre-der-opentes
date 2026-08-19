"""
Shim de compatibilidade — redireciona para inverter.inverter.

Mantido para que cenarios existentes que importam
``simulators.inverter.smart_inverter_simulator:InverterSim`` continuem funcionando.
O modelo unificado em ``simulators.inverter.inverter`` cobre toda a funcionalidade.
"""

import mosaik_api_v3

from .inverter import InverterModel

META = {
    "api_version": "3.0",
    "type": "time-based",
    "models": {
        "Inverter": {
            "public": True,
            "params": [
                "kVA",
                "eff_curve_x",
                "eff_curve_y",
                "ctrl_config",
                "phase_mode",
            ],
            "attrs": [
                "P_dc",
                "V_meas_1",
                "V_meas_2",
                "V_meas_3",
                "P_ac",
                "Q_ac",
                "P_ac_1",
                "Q_ac_1",
                "P_ac_2",
                "Q_ac_2",
                "P_ac_3",
                "Q_ac_3",
            ],
        },
    },
}


class InverterSim(mosaik_api_v3.Simulator):
    def __init__(self):
        super().__init__(META)
        self.sid = None
        self.entities = {}
        self.step_size = None

    def init(self, sid, time_resolution=1.0, step_size=900):
        self.sid = sid
        self.step_size = step_size
        return self.meta

    def create(self, num, model, **model_params):
        entities = []
        for i in range(num):
            eid = f"{model}_{len(self.entities) + i}"
            inv_model = InverterModel(
                kVA=model_params.get("kVA", 1000.0),
                eff_curve_x=model_params.get("eff_curve_x", [0.0, 1.0]),
                eff_curve_y=model_params.get("eff_curve_y", [1.0, 1.0]),
                ctrl_config=model_params.get("ctrl_config", {"Const_PF": True, "PF": 1.0}),
                phase_mode=model_params.get("phase_mode", "AVG"),
            )
            self.entities[eid] = inv_model
            entities.append({"eid": eid, "type": model})
        return entities

    def step(self, time, inputs, max_advance):
        for eid, attrs in inputs.items():
            inv = self.entities[eid]
            if "P_dc" in attrs:
                inv.P_dc = float(list(attrs["P_dc"].values())[0])
            if "V_meas_1" in attrs:
                inv.V_meas[0] = float(list(attrs["V_meas_1"].values())[0])
            if "V_meas_2" in attrs:
                inv.V_meas[1] = float(list(attrs["V_meas_2"].values())[0])
            if "V_meas_3" in attrs:
                inv.V_meas[2] = float(list(attrs["V_meas_3"].values())[0])

        for inv in self.entities.values():
            inv.calculate_step()

        return time + self.step_size

    def get_data(self, outputs):
        data = {}
        for eid, attrs in outputs.items():
            inv = self.entities[eid]
            data[eid] = {}
            for attr in attrs:
                if attr == "P_ac":
                    data[eid][attr] = sum(inv.P_ac_out)
                elif attr == "Q_ac":
                    data[eid][attr] = sum(inv.Q_ac_out)
                elif attr == "P_ac_1":
                    data[eid][attr] = inv.P_ac_out[0]
                elif attr == "Q_ac_1":
                    data[eid][attr] = inv.Q_ac_out[0]
                elif attr == "P_ac_2":
                    data[eid][attr] = inv.P_ac_out[1]
                elif attr == "Q_ac_2":
                    data[eid][attr] = inv.Q_ac_out[1]
                elif attr == "P_ac_3":
                    data[eid][attr] = inv.P_ac_out[2]
                elif attr == "Q_ac_3":
                    data[eid][attr] = inv.Q_ac_out[2]
        return data


def main():
    return mosaik_api_v3.start_simulation(InverterSim())


if __name__ == "__main__":
    main()
