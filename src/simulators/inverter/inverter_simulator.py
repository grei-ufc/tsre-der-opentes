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
                "priority",
                "eff_curve_x",
                "eff_curve_y",
                "pct_cutin",
                "pct_cutout",
            ],
            "attrs": [
                "P_dc",
                "Q_des",
                "P_ac",
                "Q_ac",
            ],
        },
    },
}


class InverterSim(mosaik_api_v3.Simulator):
    def __init__(self):
        super().__init__(META)
        self.entities = {}
        self.step_size = 1

    def init(self, sid, time_resolution=1.0, step_size=1.0):
        self.step_size = int(step_size)
        return self.meta

    def create(self, num, model, **model_params):
        entities = []
        for i in range(num):
            eid = f"{model}_{len(self.entities) + i}"

            inv_model = InverterModel(
                kVA=model_params.get("kVA", 1000.0),
                priority=model_params.get("priority", "Active"),
                eff_curve_x=model_params.get("eff_curve_x", [0.0, 1.0]),
                eff_curve_y=model_params.get("eff_curve_y", [1.0, 1.0]),
                pct_cutin=model_params.get("pct_cutin", 20.0),
                pct_cutout=model_params.get("pct_cutout", 20.0),
            )

            self.entities[eid] = inv_model
            entities.append({"eid": eid, "type": model})

        return entities

    def step(self, time, inputs, max_advance):
        for eid, attrs in inputs.items():
            inv = self.entities[eid]
            if "P_dc" in attrs:
                inv.P_dc = float(list(attrs["P_dc"].values())[0])
            if "Q_des" in attrs:
                inv.Q_des = float(list(attrs["Q_des"].values())[0])

        for inv in self.entities.values():
            inv.calculate_step()

        return time + self.step_size

    def get_data(self, outputs):
        data = {}
        for eid, attrs in outputs.items():
            inv = self.entities[eid]
            data[eid] = {}
            for attr in attrs:
                if hasattr(inv, attr):
                    data[eid][attr] = getattr(inv, attr)
        return data


if __name__ == "__main__":
    mosaik_api_v3.start_simulation(InverterSim())
