"""Voltage regulator control logic and mosaik adapter.

Contains the pure-Python ``VR_Model`` (tap-changer logic with LDC
compensation) and the ``RegulatorSimulator`` mosaik time-based adapter.
"""

import mosaik_api_v3


class VR_Model:
    """Pure-Python voltage regulator tap-changer model.

    Implements line-drop compensation (LDC), hysteresis-based over/under
    voltage detection, and timed tap actions following the OpenDER
    interface pattern.

    Attributes:
        name: Identifier for this regulator instance.
        Ts: Simulation time step (s).
        Td_ctrl: Control delay before a tap change is allowed (s).
        Td_tap: Minimum time between consecutive tap changes (s).
        Vref: Reference voltage at the PT secondary (V).
        db: Dead-band width around Vref (V).
        PT_Ratio: Potential-transformer ratio (primary / secondary).
        CT_Primary: Current-transformer primary rating (A).
        LDC_R: Line-drop resistive component (ohms referred to primary).
        LDC_X: Line-drop reactive component (ohms referred to primary).
        tap_max: Maximum tap position.
        tap_min: Minimum tap position.
        tap: Current tap position.
    """

    def __init__(
        self,
        name: str,
        Ts: float,
        Td_ctrl: float = 30,
        Td_tap: float = 2,
        Vref: float = 120,
        db: float = 2,
        PT_Ratio: float = 20,
        CT_Primary: float = 700,
        LDC_R: float = 0,
        LDC_X: float = 0,
        tap_max: int = 16,
        tap_min: int = -16,
        tap_ini: int = 0,
        **kwargs: object,
    ) -> None:
        self.name = name
        self.Ts = Ts
        self.Td_ctrl = Td_ctrl
        self.Td_tap = Td_tap
        self.Vref = Vref
        self.db = db
        self.PT_Ratio = PT_Ratio
        self.CT_Primary = CT_Primary
        self.LDC_R = LDC_R
        self.LDC_X = LDC_X
        self.tap_max = tap_max
        self.tap_min = tap_min
        self.tap = tap_ini

        # Internal state variables
        self.Ti_ctrl: float = 0
        self.Ti_tap: float = Td_tap
        self.state: str = "Idle"

        self._z_comp: complex = complex(self.LDC_R, self.LDC_X) / 5
        self._CT: float = self.CT_Primary / 5

    def run(self, V_meas: float, I_meas: float = 0) -> int:
        """Calculate the new tap position based on measured voltage.

        Args:
            V_meas: Measured voltage on the primary side (V).
            I_meas: Measured current on the primary side (A).

        Returns:
            New integer tap position after applying the control logic.
        """
        # Secondary-side voltage via PT ratio
        Vsec = V_meas / self.PT_Ratio if self.PT_Ratio > 0 else V_meas

        # LDC compensation
        Vdrop: complex = 0
        if self.CT_Primary > 0:
            I_norm = I_meas / self._CT
            Vdrop = I_norm * self._z_comp

        Vreg = abs(Vsec - Vdrop)

        # Hysteresis logic
        if Vreg > self.Vref + self.db / 2:
            target_state = "OV"
        elif Vreg < self.Vref - self.db / 2:
            target_state = "UV"
        else:
            target_state = "Idle"

        if target_state != "Idle":
            if self.state == target_state:
                self.Ti_ctrl += self.Ts
            else:
                self.state = target_state
                self.Ti_ctrl = 0
        else:
            self.state = "Idle"
            self.Ti_ctrl = 0

        self.Ti_tap += self.Ts

        # Tap actuation
        if self.Ti_ctrl > self.Td_ctrl:  # noqa: SIM102
            if self.Ti_tap >= self.Td_tap:
                if self.state == "OV" and self.tap > self.tap_min:
                    self.tap -= 1
                    self.Ti_tap = 0
                elif self.state == "UV" and self.tap < self.tap_max:
                    self.tap += 1
                    self.Ti_tap = 0

        return int(self.tap)


# --- Mosaik wrapper ---

META = {
    "api_version": "3.0",
    "type": "time-based",
    "models": {
        "RegController": {
            "public": True,
            "params": [
                "vreg",
                "band",
                "pt_ratio",
                "ct_primary",
                "R",
                "X",
                "delay",
                "tap_delay",
                "tap_ini",
            ],
            "attrs": ["v_meas", "i_meas", "tap_cmd"],  # v_meas (input), tap_cmd (output)
        },
    },
}


class RegulatorSimulator(mosaik_api_v3.Simulator):
    def __init__(self):
        super().__init__(META)
        self.controllers = {}
        self.step_size = None

    def init(self, sid, time_resolution, step_size=60):
        self.sid = sid
        self.step_size = step_size
        return self.meta

    def create(self, num, model, **model_params):
        entities = []
        for _i in range(num):
            eid = f"Ctrl-{len(self.controllers)}"

            # Instantiate pure-Python logic
            logic = VR_Model(
                name=eid,
                Ts=self.step_size,  # Important: time step defines reaction speed
                Td_ctrl=model_params.get("delay", 30),
                Td_tap=model_params.get("tap_delay", 2),
                Vref=model_params.get("vreg", 120),
                db=model_params.get("band", 2),
                PT_Ratio=model_params.get("pt_ratio", 1),
                CT_Primary=model_params.get("ct_primary", 0),
                LDC_R=model_params.get("R", 0),
                LDC_X=model_params.get("X", 0),
                tap_ini=model_params.get("tap_ini", 0),
            )

            self.controllers[eid] = logic
            entities.append({"eid": eid, "type": model})
        return entities

    def step(self, time, inputs, max_advance):
        for eid, logic in self.controllers.items():
            v = next(iter(inputs[eid]["v_meas"].values())) if "v_meas" in inputs.get(eid, {}) else 0
            i = next(iter(inputs[eid]["i_meas"].values())) if "i_meas" in inputs.get(eid, {}) else 0

            if time < 2400:
                print(f"[{time}s] {eid}: V_pri={v:.1f}V | I_pri={i:.1f}A | Tap={logic.tap}")
                # Execute logic
            logic.run(V_meas=v, I_meas=i)

        return time + self.step_size

    def get_data(self, outputs):
        data = {}
        for eid, attrs in outputs.items():
            logic = self.controllers.get(eid)
            if logic and "tap_cmd" in attrs:
                data[eid] = {"tap_cmd": logic.tap}
        return data


if __name__ == "__main__":
    mosaik_api_v3.start_simulation(RegulatorSimulator())
