"""Testes do inversor inteligente: configuração, fábrica OpenDER e modelo.

As curvas são conferidas contra os valores analíticos da IEEE 1547, e não
contra o que o código produz hoje — é isso que torna o teste capaz de detectar
uma tradução errada para os parâmetros do OpenDER.
"""

import sys

import pytest

sys.path.insert(0, "src")

from simulators.inverter.config import (
    ConfigError,
    ConstPF,
    ConstQ,
    ControlConfig,
    InverterUnit,
    PhaseMode,
    ReactiveMode,
    VoltVarCurve,
    VoltWattCurve,
)
from simulators.inverter.opender_factory import (
    OpenDERSetupError,
    build_der_file,
    current_time_step,
    der_params,
    reset_time_step,
    set_time_step,
)
from simulators.inverter.smart_inverter import SmartInverterModel
from simulators.inverter.smart_inverter_simulator import (
    INPUT_SPECS,
    META,
    OUTPUT_GETTERS,
    SmartInverterSim,
)

STEP = 300.0
KV_LL = 4.16
KV_LN = 2.4


@pytest.fixture(autouse=True)
def _time_step():
    """``DER.t_s`` é global ao processo; fixá-lo isola os testes entre si."""
    reset_time_step()
    set_time_step(STEP)
    yield
    reset_time_step()


def make_ctrl(**kwargs):
    defaults = {
        "reactive_mode": ReactiveMode.VOLT_VAR,
        "volt_var": VoltVarCurve.ieee1547_cat_b(),
        "trip_enabled": False,
    }
    defaults.update(kwargs)
    return ControlConfig(**defaults)


def make_inverter(ctrl=None, kva=500.0, **kwargs):
    return SmartInverterModel(
        units=[InverterUnit(name="PV_test", kva=kva, kv=KV_LL, phases=3)],
        ctrl=ctrl if ctrl is not None else make_ctrl(),
        step_size=STEP,
        **kwargs,
    )


# ----------------------------------------------------------------------
# Curvas
# ----------------------------------------------------------------------


class TestVoltVarCurve:
    def test_default_is_cat_b(self):
        curve = VoltVarCurve()
        assert curve.v == (0.92, 0.98, 1.02, 1.08)
        assert curve.q == (0.44, 0.0, 0.0, -0.44)

    @pytest.mark.parametrize(
        ("v_pu", "expected"),
        [
            (0.80, 0.44),  # abaixo de V1: satura injetando
            (0.92, 0.44),  # exatamente V1
            (0.95, 0.22),  # meio do primeiro segmento
            (1.00, 0.0),  # zona morta
            (1.02, 0.0),  # exatamente V3
            (1.05, -0.22),  # meio do último segmento
            (1.08, -0.44),  # exatamente V4
            (1.20, -0.44),  # acima de V4: satura absorvendo
        ],
    )
    def test_q_at_matches_piecewise_linear(self, v_pu, expected):
        assert VoltVarCurve.ieee1547_cat_b().q_at(v_pu) == pytest.approx(expected, abs=1e-9)

    def test_rejects_non_monotonic_voltage(self):
        with pytest.raises(ConfigError, match="decrescer"):
            VoltVarCurve(v=(0.92, 1.02, 0.98, 1.08), q=(0.44, 0.0, 0.0, -0.44))

    def test_accepts_zero_width_deadband(self):
        """A curva padrão da Categoria A tem V2 = V3 = 1.0 pu."""
        curve = VoltVarCurve.ieee1547_cat_a()
        assert curve.v[1] == curve.v[2] == 1.0
        assert curve.q_at(1.0) == pytest.approx(0.0)
        assert curve.q_at(0.95) == pytest.approx(0.125)
        assert curve.q_at(1.05) == pytest.approx(-0.125)

    def test_rejects_sloped_segment_without_width(self):
        with pytest.raises(ConfigError, match="V1 deve ser menor que V2"):
            VoltVarCurve(v=(0.98, 0.98, 1.02, 1.08), q=(0.44, 0.0, 0.0, -0.44))
        with pytest.raises(ConfigError, match="V3 deve ser menor que V4"):
            VoltVarCurve(v=(0.92, 0.98, 1.02, 1.02), q=(0.44, 0.0, 0.0, -0.44))

    def test_rejects_rising_q_because_it_diverges(self):
        with pytest.raises(ConfigError, match="não crescente"):
            VoltVarCurve(v=(0.92, 0.98, 1.02, 1.08), q=(-0.44, 0.0, 0.0, 0.44))

    def test_rejects_wrong_number_of_points(self):
        with pytest.raises(ConfigError, match="esperados 4 pontos"):
            VoltVarCurve(v=(0.92, 1.08), q=(0.44, -0.44))

    def test_rejects_q_beyond_nameplate(self):
        with pytest.raises(ConfigError, match=r"\[-1, 1\]"):
            VoltVarCurve(q=(1.5, 0.0, 0.0, -0.44))

    def test_rejects_absorbing_at_undervoltage(self):
        with pytest.raises(ConfigError, match="Q1"):
            VoltVarCurve(q=(-0.1, -0.2, -0.3, -0.44))

    def test_strict_mode_rejects_out_of_standard_curve(self):
        VoltVarCurve(v=(0.80, 0.98, 1.02, 1.08), q=(0.44, 0.0, 0.0, -0.44))  # apenas informa
        with pytest.raises(ConfigError, match="QV_CURVE_V1"):
            VoltVarCurve(
                v=(0.80, 0.98, 1.02, 1.08), q=(0.44, 0.0, 0.0, -0.44), strict_ieee1547=True
            )

    def test_relaxation_is_one_when_olrt_below_step(self):
        # O filtro do OpenDER é curto-circuitado abaixo de 1.15 * t_s.
        assert VoltVarCurve(olrt=5.0).relaxation_factor(STEP) == 1.0

    def test_relaxation_damps_when_olrt_above_step(self):
        factor = VoltVarCurve(olrt=4 * STEP).relaxation_factor(STEP)
        assert 0.0 < factor < 1.0
        assert factor == pytest.approx(1 / (1 + 4 / 1.15), rel=1e-6)

    def test_der_params_order_avoids_spurious_warnings(self):
        keys = list(VoltVarCurve.ieee1547_cat_b().as_der_params())
        # V1 é validado contra V2, e V4 contra V3: os dois de referência primeiro.
        assert keys.index("QV_CURVE_V2") < keys.index("QV_CURVE_V1")
        assert keys.index("QV_CURVE_V3") < keys.index("QV_CURVE_V4")

    def test_round_trip_through_dict(self):
        curve = VoltVarCurve.ieee1547_cat_a(olrt=12.0, vref=1.01)
        assert VoltVarCurve.from_dict(curve.to_dict()) == curve


class TestVoltWattCurve:
    @pytest.mark.parametrize(
        ("v_pu", "expected"),
        [(1.00, 1.0), (1.06, 1.0), (1.08, 0.6), (1.10, 0.2), (1.15, 0.2)],
    )
    def test_p_limit_matches_piecewise_linear(self, v_pu, expected):
        assert VoltWattCurve.ieee1547_default().p_limit_at(v_pu) == pytest.approx(expected)

    def test_rejects_rising_power(self):
        with pytest.raises(ConfigError, match="não crescente"):
            VoltWattCurve(v=(1.06, 1.10), p=(0.2, 1.0))

    def test_rejects_negative_power(self):
        with pytest.raises(ConfigError, match=r"\[0, 1\]"):
            VoltWattCurve(v=(1.06, 1.10), p=(1.0, -0.2))

    def test_der_params_order_avoids_spurious_warnings(self):
        keys = list(VoltWattCurve.ieee1547_default().as_der_params())
        assert keys.index("PV_CURVE_P2") < keys.index("PV_CURVE_P1")
        assert keys.index("PV_CURVE_V1") < keys.index("PV_CURVE_V2")


# ----------------------------------------------------------------------
# Configuração
# ----------------------------------------------------------------------


class TestControlConfig:
    def test_volt_var_mode_requires_the_curve(self):
        with pytest.raises(ConfigError, match="exige o parâmetro 'volt_var'"):
            ControlConfig(reactive_mode=ReactiveMode.VOLT_VAR)

    def test_const_pf_mode_requires_the_setting(self):
        with pytest.raises(ConfigError, match="exige o parâmetro 'const_pf'"):
            ControlConfig(reactive_mode=ReactiveMode.CONST_PF)

    def test_volt_watt_is_orthogonal_to_reactive_mode(self):
        ctrl = ControlConfig(volt_watt=VoltWattCurve.ieee1547_default())
        assert ctrl.reactive_mode is ReactiveMode.NONE
        assert ctrl.uses_opender

    def test_no_function_means_no_opender(self):
        assert not ControlConfig().uses_opender

    def test_rejects_unknown_priority(self):
        with pytest.raises(ConfigError, match="priority"):
            ControlConfig(priority="Whatever")

    def test_rejects_unknown_q_capability_low_p(self):
        with pytest.raises(ConfigError, match="q_capability_low_p"):
            ControlConfig(q_capability_low_p="ZERO")

    def test_coerce_accepts_dict_from_remote_scenario(self):
        payload = make_ctrl().to_dict()
        ctrl = ControlConfig.coerce(payload)
        assert ctrl.reactive_mode is ReactiveMode.VOLT_VAR
        assert ctrl.volt_var == VoltVarCurve.ieee1547_cat_b()

    def test_round_trip_preserves_every_field(self):
        ctrl = ControlConfig(
            reactive_mode=ReactiveMode.CONST_PF,
            const_pf=ConstPF(pf=0.95, excitation="INJ"),
            volt_watt=VoltWattCurve.ieee1547_default(),
            trip_enabled=False,
            priority="ACTIVE",
            v_meas_unbalance="POS",
        )
        assert ControlConfig.from_dict(ctrl.to_dict()) == ctrl

    def test_only_the_selected_mode_is_enabled(self):
        params = make_ctrl().as_der_params()
        assert params["QV_MODE_ENABLE"] is True
        assert "CONST_PF_MODE_ENABLE" not in params
        assert "CONST_Q_MODE_ENABLE" not in params

    def test_trip_thresholds_are_untouched_when_enabled(self):
        params = ControlConfig(trip_enabled=True).as_der_params()
        assert not any(key.endswith(("_TRIP_V", "_TRIP_F", "_TRIP_T")) for key in params)


class TestInverterUnit:
    def test_single_phase_requires_a_node(self):
        with pytest.raises(ConfigError, match="node"):
            InverterUnit(name="PV", kva=10.0, kv=KV_LN, phases=1)

    def test_rejects_two_phase(self):
        with pytest.raises(ConfigError, match="phases"):
            InverterUnit(name="PV", kva=10.0, kv=KV_LN, phases=2)

    def test_nodes_of_three_phase_unit(self):
        unit = InverterUnit(name="PV", kva=10.0, kv=KV_LL)
        assert unit.nodes == (1, 2, 3)
        assert unit.phase_mode is PhaseMode.THREE

    def test_nodes_of_single_phase_unit(self):
        unit = InverterUnit(name="PV", kva=10.0, kv=KV_LN, phases=1, node=2)
        assert unit.nodes == (2,)
        assert unit.phase_mode is PhaseMode.SINGLE

    def test_kw_defaults_to_kva(self):
        assert InverterUnit(name="PV", kva=10.0).kw_rating == 10.0


# ----------------------------------------------------------------------
# Fábrica OpenDER
# ----------------------------------------------------------------------


class TestOpenDERFactory:
    def test_time_step_reaches_opender(self):
        from opender import DER

        set_time_step(60.0)
        assert DER.t_s == 60.0
        assert current_time_step() == 60.0

    def test_rejects_non_positive_time_step(self):
        with pytest.raises(ValueError, match="> 0"):
            set_time_step(0)

    def test_kv_is_required_when_opender_is_active(self):
        unit = InverterUnit(name="PV", kva=100.0)  # sem kv
        with pytest.raises(OpenDERSetupError, match="'kv' é obrigatório"):
            build_der_file(unit, make_ctrl())

    def test_apparent_power_is_written_before_reactive_capability(self):
        keys = list(der_params(InverterUnit(name="PV", kva=500.0, kv=KV_LL), make_ctrl()))
        assert keys.index("NP_VA_MAX") < keys.index("NP_Q_MAX_INJ")
        assert keys.index("NP_VA_MAX") < keys.index("NP_Q_MAX_ABS")
        assert keys.index("NP_Q_MAX_ABS") < keys.index("NP_Q_CAPABILITY_LOW_P")

    def test_dc_voltage_is_written_before_ac_voltage(self):
        keys = list(der_params(InverterUnit(name="PV", kva=500.0, kv=KV_LL), make_ctrl()))
        assert keys.index("NP_V_DC") < keys.index("NP_AC_V_NOM")

    @pytest.mark.parametrize("kva", [50.0, 100.0, 500.0, 2000.0])
    def test_reactive_capability_tracks_the_rating(self, kva):
        """Regressão: ajustar NP_VA_MAX sem o par NP_Q_MAX_* travava Q em 44 kvar."""
        unit = InverterUnit(name="PV", kva=kva, kv=KV_LL)
        der_file = build_der_file(unit, make_ctrl())

        assert der_file.NP_VA_MAX == pytest.approx(kva * 1000.0)
        assert der_file.NP_Q_MAX_INJ == pytest.approx(0.44 * kva * 1000.0)
        curve = der_file.NP_Q_CAPABILITY_BY_P_CURVE
        assert curve["Q_MAX_INJ_PU"][-1] == pytest.approx(0.44)
        assert curve["Q_MAX_ABS_PU"][-1] == pytest.approx(0.44)

    def test_nominal_voltage_uses_line_to_line_for_three_phase(self):
        der_file = build_der_file(InverterUnit(name="PV", kva=100.0, kv=KV_LL), make_ctrl())
        assert der_file.NP_AC_V_NOM == pytest.approx(4160.0)
        assert der_file.NP_PHASE == "THREE"

    def test_nominal_voltage_uses_line_to_neutral_for_single_phase(self):
        unit = InverterUnit(name="PV", kva=100.0, kv=KV_LN, phases=1, node=1)
        der_file = build_der_file(unit, make_ctrl())
        assert der_file.NP_AC_V_NOM == pytest.approx(2400.0)
        assert der_file.NP_PHASE == "SINGLE"

    def test_custom_reactive_capability_is_honoured(self):
        unit = InverterUnit(name="PV", kva=100.0, kv=KV_LL, q_inj_pu=0.6, q_abs_pu=0.5)
        curve = build_der_file(unit, make_ctrl()).NP_Q_CAPABILITY_BY_P_CURVE
        assert curve["Q_MAX_INJ_PU"][-1] == pytest.approx(0.6)
        assert curve["Q_MAX_ABS_PU"][-1] == pytest.approx(0.5)


# ----------------------------------------------------------------------
# Modelo: volt-var
# ----------------------------------------------------------------------


class TestVoltVarEndToEnd:
    @pytest.mark.parametrize(
        ("v_pu", "q_pu"),
        [(0.90, 0.44), (0.95, 0.22), (1.00, 0.0), (1.05, -0.22), (1.08, -0.44)],
    )
    def test_reproduces_the_curve(self, v_pu, q_pu):
        inv = make_inverter(kva=500.0)
        inv.P_dc = 250.0
        inv.V_meas = [v_pu, v_pu, v_pu]
        inv.calculate_step()
        assert inv.Q_ac == pytest.approx(q_pu * 500.0, abs=0.01)
        assert inv.P_ac == pytest.approx(250.0, abs=0.01)

    def test_saturates_at_the_reactive_capability(self):
        inv = make_inverter(kva=500.0)
        inv.P_dc = 250.0
        inv.V_meas = [1.12, 1.12, 1.12]  # acima de V4, dentro do ride-through
        inv.calculate_step()
        assert inv.Q_ac == pytest.approx(-220.0, abs=0.01)

    def test_custom_curve_shifts_the_deadband(self):
        ctrl = make_ctrl(volt_var=VoltVarCurve(v=(0.90, 0.99, 1.01, 1.06), q=(0.3, 0.0, 0.0, -0.3)))
        inv = make_inverter(ctrl=ctrl, kva=100.0)
        inv.P_dc = 50.0
        inv.V_meas = [1.06, 1.06, 1.06]
        inv.calculate_step()
        assert inv.Q_ac == pytest.approx(-30.0, abs=0.01)

    def test_no_reactive_at_night_with_reduced_capability(self):
        """Comportamento padrão do OpenDER: sem P, sem capacidade de reativo."""
        inv = make_inverter(kva=500.0)
        inv.P_dc = 0.0
        inv.V_meas = [1.08, 1.08, 1.08]
        inv.calculate_step()
        assert inv.Q_ac == pytest.approx(0.0, abs=0.01)

    def test_night_time_volt_var_with_same_capability(self):
        inv = make_inverter(ctrl=make_ctrl(q_capability_low_p="SAME"), kva=500.0)
        inv.P_dc = 0.0
        inv.V_meas = [1.08, 1.08, 1.08]
        inv.calculate_step()
        assert inv.Q_ac == pytest.approx(-220.0, abs=0.01)

    def test_reactive_priority_reduces_active_power(self):
        """Com P na potência nominal, Q só cabe se P recuar (prioridade REACTIVE)."""
        inv = make_inverter(kva=500.0)
        inv.P_dc = 500.0
        inv.V_meas = [1.08, 1.08, 1.08]
        inv.calculate_step()
        assert inv.Q_ac == pytest.approx(-220.0, abs=0.01)
        assert inv.P_ac == pytest.approx((500.0**2 - 220.0**2) ** 0.5, abs=0.5)


class TestVoltWattEndToEnd:
    @pytest.mark.parametrize(
        ("v_pu", "p_kw"), [(1.00, 500.0), (1.06, 500.0), (1.08, 300.0), (1.10, 100.0)]
    )
    def test_limits_active_power(self, v_pu, p_kw):
        ctrl = ControlConfig(volt_watt=VoltWattCurve.ieee1547_default(), trip_enabled=False)
        inv = make_inverter(ctrl=ctrl, kva=500.0)
        inv.P_dc = 500.0
        inv.V_meas = [v_pu, v_pu, v_pu]
        inv.calculate_step()
        assert inv.P_ac == pytest.approx(p_kw, abs=0.01)

    def test_does_not_raise_power_above_what_is_available(self):
        ctrl = ControlConfig(volt_watt=VoltWattCurve.ieee1547_default(), trip_enabled=False)
        inv = make_inverter(ctrl=ctrl, kva=500.0)
        inv.P_dc = 100.0
        inv.V_meas = [1.00, 1.00, 1.00]
        inv.calculate_step()
        assert inv.P_ac == pytest.approx(100.0, abs=0.01)

    def test_runs_together_with_volt_var(self):
        ctrl = make_ctrl(volt_watt=VoltWattCurve.ieee1547_default())
        inv = make_inverter(ctrl=ctrl, kva=500.0)
        inv.P_dc = 500.0
        inv.V_meas = [1.08, 1.08, 1.08]
        inv.calculate_step()
        # Volt-watt limita P a 0.6 pu; volt-var pede -0.44 pu de Q. Os dois
        # cabem no círculo de S, então nenhum é reduzido pelo outro.
        assert inv.P_ac == pytest.approx(300.0, abs=0.5)
        assert inv.Q_ac == pytest.approx(-220.0, abs=0.5)


class TestConstantModes:
    def test_const_pf_absorbing(self):
        ctrl = ControlConfig(
            reactive_mode=ReactiveMode.CONST_PF,
            const_pf=ConstPF(pf=0.9, excitation="ABS"),
            trip_enabled=False,
        )
        inv = make_inverter(ctrl=ctrl, kva=500.0)
        inv.P_dc = 300.0
        inv.V_meas = [1.0, 1.0, 1.0]
        inv.calculate_step()
        expected_q = -300.0 * (1 - 0.9**2) ** 0.5 / 0.9
        assert inv.Q_ac == pytest.approx(expected_q, rel=1e-3)

    def test_const_q(self):
        ctrl = ControlConfig(
            reactive_mode=ReactiveMode.CONST_Q, const_q=ConstQ(q=-0.3), trip_enabled=False
        )
        inv = make_inverter(ctrl=ctrl, kva=500.0)
        inv.P_dc = 250.0
        inv.V_meas = [1.0, 1.0, 1.0]
        inv.calculate_step()
        assert inv.Q_ac == pytest.approx(-150.0, abs=0.01)


# ----------------------------------------------------------------------
# Modelo: unidades monofásicas
# ----------------------------------------------------------------------


class TestSinglePhaseUnits:
    @staticmethod
    def build():
        units = [
            InverterUnit(name=f"PV_{n}", kva=100.0, kv=KV_LN, phases=1, node=n) for n in (1, 2, 3)
        ]
        return SmartInverterModel(units=units, ctrl=make_ctrl(), step_size=STEP)

    def test_each_unit_responds_to_its_own_phase(self):
        inv = self.build()
        inv.P_dc = 150.0
        inv.V_meas = [1.05, 1.00, 0.95]
        inv.calculate_step()

        assert inv.unit_q[0] == pytest.approx(-22.0, abs=0.01)  # 1.05 -> -0.22 pu
        assert inv.unit_q[1] == pytest.approx(0.0, abs=0.01)  # zona morta
        assert inv.unit_q[2] == pytest.approx(22.0, abs=0.01)  # 0.95 -> +0.22 pu

    def test_phase_totals_match_unit_totals(self):
        inv = self.build()
        inv.P_dc = 150.0
        inv.V_meas = [1.05, 1.00, 0.95]
        inv.calculate_step()

        for node in (1, 2, 3):
            assert inv.phase_q[node - 1] == pytest.approx(inv.unit_q[node - 1])
        assert sum(inv.unit_p) == pytest.approx(inv.P_ac)
        assert sum(inv.phase_q) == pytest.approx(inv.Q_ac)

    def test_available_power_is_shared_by_rating(self):
        units = [
            InverterUnit(name="PV_big", kva=200.0, kv=KV_LN, phases=1, node=1),
            InverterUnit(name="PV_small", kva=100.0, kv=KV_LN, phases=1, node=2),
        ]
        inv = SmartInverterModel(units=units, ctrl=make_ctrl(), step_size=STEP)
        inv.P_dc = 150.0
        inv.V_meas = [1.0, 1.0, 1.0]
        inv.calculate_step()
        assert inv.unit_p[0] == pytest.approx(100.0, abs=0.01)
        assert inv.unit_p[1] == pytest.approx(50.0, abs=0.01)

    def test_missing_voltage_is_an_error_not_a_silent_default(self):
        inv = self.build()
        inv.P_dc = 150.0
        inv.V_meas = [1.05, None, 0.95]
        with pytest.raises(OpenDERSetupError, match="V_meas_2"):
            inv.calculate_step()

    def test_two_units_on_the_same_node_are_rejected(self):
        units = [
            InverterUnit(name="PV_a", kva=100.0, kv=KV_LN, phases=1, node=1),
            InverterUnit(name="PV_b", kva=100.0, kv=KV_LN, phases=1, node=1),
        ]
        with pytest.raises(ValueError, match="nó 1"):
            SmartInverterModel(units=units, ctrl=make_ctrl(), step_size=STEP)

    def test_three_phase_unit_splits_evenly_across_phases(self):
        inv = make_inverter(kva=300.0)
        inv.P_dc = 150.0
        inv.V_meas = [1.0, 1.0, 1.0]
        inv.calculate_step()
        assert inv.phase_p == pytest.approx([50.0, 50.0, 50.0], abs=0.01)


# ----------------------------------------------------------------------
# Modelo: caminho sem OpenDER
# ----------------------------------------------------------------------


class TestPassthrough:
    @staticmethod
    def build(**kwargs):
        return SmartInverterModel(
            units=[InverterUnit(name="PV", kva=100.0)],
            ctrl=ControlConfig(**kwargs.pop("ctrl", {})),
            step_size=STEP,
            **kwargs,
        )

    def test_follows_q_des(self):
        inv = self.build()
        inv.P_dc, inv.Q_des = 50.0, 20.0
        inv.calculate_step()
        assert inv.P_ac == pytest.approx(50.0)
        assert inv.Q_ac == pytest.approx(20.0)

    def test_cut_in_hysteresis(self):
        inv = self.build(pct_cutin=20.0, pct_cutout=10.0)

        inv.P_dc = 15.0  # 15% < cut-in
        inv.calculate_step()
        assert inv.is_on is False

        inv.P_dc = 25.0  # acima do cut-in: liga
        inv.calculate_step()
        assert inv.is_on is True

        inv.P_dc = 15.0  # entre cut-out e cut-in: continua ligado
        inv.calculate_step()
        assert inv.is_on is True

        inv.P_dc = 5.0  # abaixo do cut-out: desliga
        inv.calculate_step()
        assert inv.is_on is False
        assert inv.P_ac == 0.0

    def test_efficiency_curve(self):
        inv = self.build(eff_curve_x=[0.0, 1.0], eff_curve_y=[0.9, 0.9])
        inv.P_dc = 50.0
        inv.calculate_step()
        assert inv.P_ac == pytest.approx(45.0)

    def test_reactive_priority_clamps_active_power(self):
        inv = self.build(ctrl={"priority": "REACTIVE"})
        inv.P_dc, inv.Q_des = 100.0, 60.0
        inv.calculate_step()
        assert inv.Q_ac == pytest.approx(60.0)
        assert inv.P_ac == pytest.approx(80.0, abs=0.01)

    def test_active_priority_clamps_reactive_power(self):
        inv = self.build(ctrl={"priority": "ACTIVE"})
        inv.P_dc, inv.Q_des = 80.0, 90.0
        inv.calculate_step()
        assert inv.P_ac == pytest.approx(80.0)
        assert inv.Q_ac == pytest.approx(60.0, abs=0.01)


# ----------------------------------------------------------------------
# Trip
# ----------------------------------------------------------------------


class TestTrip:
    def test_overvoltage_trips_when_enabled(self):
        inv = make_inverter(ctrl=make_ctrl(trip_enabled=True), kva=500.0)
        inv.P_dc = 250.0
        inv.V_meas = [1.15, 1.15, 1.15]
        inv.calculate_step()
        assert inv.der_status == "Trip"
        assert inv.P_ac == pytest.approx(0.0, abs=1e-6)

    def test_no_trip_when_disabled(self):
        inv = make_inverter(ctrl=make_ctrl(trip_enabled=False), kva=500.0)
        inv.P_dc = 250.0
        inv.V_meas = [1.15, 1.15, 1.15]
        inv.calculate_step()
        assert inv.der_status != "Trip"
        assert inv.P_ac > 0.0

    def test_undervoltage_trips_when_enabled(self):
        inv = make_inverter(ctrl=make_ctrl(trip_enabled=True), kva=500.0)
        inv.P_dc = 250.0
        inv.V_meas = [0.4, 0.4, 0.4]
        inv.calculate_step()
        assert inv.der_status == "Trip"

    def test_no_undervoltage_trip_when_disabled(self):
        inv = make_inverter(ctrl=make_ctrl(trip_enabled=False), kva=500.0)
        inv.P_dc = 250.0
        inv.V_meas = [0.4, 0.4, 0.4]
        inv.calculate_step()
        assert inv.der_status != "Trip"

    def test_disabling_trip_moves_thresholds_out_of_range(self):
        """Esticar a duração não bastaria: o temporizador começa em infinito."""
        params = ControlConfig(trip_enabled=False).as_der_params()
        assert params["OV1_TRIP_V"] > 10.0
        assert params["UV1_TRIP_V"] == 0.0
        assert params["OF1_TRIP_F"] > 1000.0
        assert "OV1_TRIP_T" not in params


# ----------------------------------------------------------------------
# Adaptador mosaik
# ----------------------------------------------------------------------


class TestAdapter:
    def test_meta_declares_only_implemented_attributes(self):
        declared = set(META["models"]["Inverter"]["attrs"])
        implemented = set(INPUT_SPECS) | set(OUTPUT_GETTERS)
        assert declared == implemented

    def test_meta_has_no_duplicate_attributes(self):
        attrs = META["models"]["Inverter"]["attrs"]
        assert len(attrs) == len(set(attrs))

    def test_init_sets_the_global_time_step(self):
        from opender import DER

        sim = SmartInverterSim()
        sim.init("Sim-0", time_resolution=1.0, step_size=900)
        assert DER.t_s == 900.0

    def test_init_scales_by_time_resolution(self):
        from opender import DER

        sim = SmartInverterSim()
        sim.init("Sim-0", time_resolution=60.0, step_size=5)
        assert DER.t_s == 300.0

    def test_single_unit_shortcut(self):
        sim = SmartInverterSim()
        sim.init("Sim-0", step_size=STEP)
        created = sim.create(1, "Inverter", kVA=500.0, kv=KV_LL, ctrl_config=make_ctrl().to_dict())
        assert created == [{"eid": "Inverter_0", "type": "Inverter"}]
        assert sim.entities["Inverter_0"].kva_total == 500.0

    def test_explicit_units(self):
        sim = SmartInverterSim()
        sim.init("Sim-0", step_size=STEP)
        units = [
            InverterUnit(name=f"PV_{n}", kva=100.0, kv=KV_LN, phases=1, node=n).to_dict()
            for n in (1, 2, 3)
        ]
        sim.create(1, "Inverter", units=units, ctrl_config=make_ctrl().to_dict())
        assert len(sim.entities["Inverter_0"].units) == 3

    def test_rejects_more_units_than_outputs(self):
        sim = SmartInverterSim()
        sim.init("Sim-0", step_size=STEP)
        units = [InverterUnit(name=f"PV_{i}", kva=10.0, kv=KV_LN).to_dict() for i in range(4)]
        with pytest.raises(ConfigError, match="no máximo 3"):
            sim.create(1, "Inverter", units=units)

    def test_legacy_priority_parameter_still_works(self):
        sim = SmartInverterSim()
        sim.init("Sim-0", step_size=STEP)
        sim.create(1, "Inverter", kVA=100.0, priority="Active")
        assert sim.entities["Inverter_0"].ctrl.priority == "ACTIVE"

    def test_legacy_priority_conflicting_with_ctrl_config_is_rejected(self):
        sim = SmartInverterSim()
        sim.init("Sim-0", step_size=STEP)
        with pytest.raises(ConfigError, match="conflita"):
            sim.create(
                1,
                "Inverter",
                kVA=100.0,
                priority="Active",
                ctrl_config=ControlConfig(priority="REACTIVE").to_dict(),
            )

    def test_step_and_get_data_round_trip(self):
        sim = SmartInverterSim()
        sim.init("Sim-0", step_size=STEP)
        sim.create(1, "Inverter", kVA=500.0, kv=KV_LL, ctrl_config=make_ctrl().to_dict())

        next_time = sim.step(
            0,
            {
                "Inverter_0": {
                    "P_dc": {"PV-0.Panel_0": 250.0},
                    "V_meas_1": {"DSS-0.Bus-1": 1.05},
                    "V_meas_2": {"DSS-0.Bus-1": 1.05},
                    "V_meas_3": {"DSS-0.Bus-1": 1.05},
                }
            },
            STEP,
        )
        assert next_time == STEP

        data = sim.get_data({"Inverter_0": ["P_ac", "Q_ac", "P_ac_1", "der_status", "V_meas_pu"]})
        values = data["Inverter_0"]
        assert values["P_ac"] == pytest.approx(250.0, abs=0.01)
        assert values["Q_ac"] == pytest.approx(-110.0, abs=0.01)
        assert values["P_ac_1"] == pytest.approx(250.0, abs=0.01)
        assert values["der_status"] == "Continuous Operation"
        assert values["V_meas_pu"] == pytest.approx(1.05, abs=1e-6)

    def test_power_inputs_are_summed_across_sources(self):
        sim = SmartInverterSim()
        sim.init("Sim-0", step_size=STEP)
        sim.create(1, "Inverter", kVA=500.0)
        sim.step(0, {"Inverter_0": {"P_dc": {"PV-0.A": 100.0, "PV-0.B": 150.0}}}, STEP)
        assert sim.entities["Inverter_0"].P_ac == pytest.approx(250.0)

    def test_unknown_model_is_rejected(self):
        sim = SmartInverterSim()
        sim.init("Sim-0", step_size=STEP)
        with pytest.raises(ValueError, match="modelo desconhecido"):
            sim.create(1, "Panel")
