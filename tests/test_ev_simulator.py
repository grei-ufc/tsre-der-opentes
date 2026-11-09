"""Unit tests for the EV simulator (CalderaWrapper, CalderaEVSim, and Load P/Q control)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

sys.path.insert(0, "src")

from simulators.ev.caldera_ev_sim import CalderaEVModel, CalderaEVSim
from simulators.ev.caldera_wrapper import CalderaWrapper
from simulators.opendss.element_specs import MODEL_SPECS, write_load
from simulators.util.ev_creator import alocar_evs


class TestCalderaWrapper:
    @pytest.fixture
    def wrapper(self):
        return CalderaWrapper()

    def test_charger_mapping(self, wrapper):
        assert wrapper.get_charger_for_vehicle("BYD DOLPHIN MINI GS5EV") == "BYD_Wallbox_7kW"
        assert wrapper.get_charger_for_vehicle("GWM ORA 03 SKIN") == "GWM_Wallbox_Serie_G"
        assert wrapper.get_charger_for_vehicle("HAVAL H6 PHEV") == "GWM_Wallbox_Serie_G"
        assert wrapper.get_charger_for_vehicle("GEELY EX2 MAX") == "Geely_Padrao_6p6kW"
        assert wrapper.get_charger_for_vehicle("UNKNOWN_CAR") == wrapper.DEFAULT_CHARGER

    def test_get_charge_profile_valid(self, wrapper):
        profile = wrapper.get_charge_profile("BYD DOLPHIN MINI GS5EV", 0.20, 0.80)
        assert isinstance(profile, list)
        assert len(profile) > 0
        assert max(profile) > 3.0  # Should reach nominal charging power

    def test_get_charge_profile_edge_cases(self, wrapper):
        # Target SoC <= Initial SoC should return empty profile
        assert wrapper.get_charge_profile("BYD DOLPHIN MINI GS5EV", 0.80, 0.80) == []
        assert wrapper.get_charge_profile("BYD DOLPHIN MINI GS5EV", 0.90, 0.50) == []
        # Almost full battery
        assert wrapper.get_charge_profile("BYD DOLPHIN MINI GS5EV", 0.996, 1.0) == []

    def test_caching(self, wrapper):
        p1 = wrapper.get_charge_profile("BYD DOLPHIN MINI GS5EV", 0.30, 0.70)
        p2 = wrapper.get_charge_profile("BYD DOLPHIN MINI GS5EV", 0.30, 0.70)
        assert p1 is p2


class TestCalderaEVModel:
    def test_model_initialization_and_step(self):
        power_series = np.array([0.0, 3.6, 7.2, 0.0])
        model = CalderaEVModel(
            eid="EV_0", profile_name="test_prof", power_series=power_series, fp=0.98
        )

        assert model.eid == "EV_0"
        assert model.fp == 0.98
        assert model.tan_phi > 0.0

        # Step 0 (0 min) -> power = 0.0
        model.update_step(0)
        assert model.P_kw == 0.0
        assert model.Q_kvar == 0.0
        assert not model.is_charging

        # Step 1 (1 min) -> power = 3.6
        model.update_step(1)
        assert model.P_kw == 3.6
        assert model.Q_kvar > 0.0
        assert model.is_charging

        # Step 2 (2 min) -> power = 7.2
        model.update_step(2)
        assert model.P_kw == 7.2
        assert model.is_charging

    def test_unity_power_factor(self):
        power_series = np.array([5.0])
        model = CalderaEVModel(
            eid="EV_1", profile_name="test_prof", power_series=power_series, fp=1.0
        )
        model.update_step(0)
        assert model.P_kw == 5.0
        assert model.Q_kvar == 0.0


class TestCalderaEVSim:
    def test_meta_compliance(self):
        sim = CalderaEVSim()
        assert sim.meta["api_version"] == "3.0"
        assert sim.meta["type"] == "time-based"
        assert "CalderaEV" in sim.meta["models"]
        attrs = sim.meta["models"]["CalderaEV"]["attrs"]
        assert "P_kw" in attrs
        assert "Q_kvar" in attrs
        assert "fp" in attrs
        assert "is_charging" in attrs

    def test_init_and_create(self):
        sim = CalderaEVSim()
        meta = sim.init("CalderaEV-0", step_size=600)
        assert meta == sim.meta

        entities = sim.create(1, "CalderaEV", profile_name="User_1_semana_1_7p2kW")
        assert len(entities) == 1
        assert entities[0]["eid"] == "CalderaEV_0"

        # Advance step
        sim.step(0, {}, 600)
        data = sim.get_data({"CalderaEV_0": ["P_kw", "Q_kvar", "fp", "is_charging"]})
        assert "CalderaEV_0" in data
        assert "P_kw" in data["CalderaEV_0"]
        assert "Q_kvar" in data["CalderaEV_0"]


class TestOpenDSSLoadControl:
    def test_write_load_pq_delegation(self):
        sim_mock = MagicMock()
        write_load(sim_mock, "Load1", {"P_kw": 7.2, "Q_kvar": 1.5})
        sim_mock.dss_wrapper.set_power.assert_called_once_with(
            "Load1",
            p=7.2,
            q=1.5,
            element="Load",
        )

    def test_load_model_spec_inputs(self):
        load_spec = MODEL_SPECS["Load"]
        assert "P_kw" in load_spec.inputs
        assert "Q_kvar" in load_spec.inputs
        assert "S_mult" in load_spec.inputs


class TestEVCreator:
    def test_alocar_evs_basic(self, tmp_path):
        circuito_dss = Path("data/13Bus/IEEE13Nodeckt.dss").resolve()
        out_dss = tmp_path / "test_evs.dss"

        res = alocar_evs(
            quantidade=2,
            seed=42,
            caminho_dss=circuito_dss,
            output_dss=out_dss,
        )

        assert res["qtd_evs"] == 2
        assert out_dss.exists()
        content = out_dss.read_text(encoding="utf-8")
        assert "New Load.EV_" in content
        assert len(res["comandos_dss"]) == 2
