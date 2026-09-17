"""Presets e ligação do webvis ao grid do OpenDSS.

Não precisam de OpenDSS: ``attach_webvis`` só fala com o webvis pela API
mosaik, então os dois lados são substituídos por dublês.
"""

import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, "src")

from simulators.opendss.element_specs import MODEL_SPECS
from simulators.opendss.visualization import (
    DEFAULT_SHOW,
    MERGE_TYPES,
    PRESETS,
    attach_webvis,
    resolve_etypes,
)


class TestResolveEtypes:
    def test_names_resolve_to_presets(self):
        resolved = resolve_etypes(["Bus", "PVSystem"])

        assert resolved == {"Bus": PRESETS["Bus"], "PVSystem": PRESETS["PVSystem"]}

    def test_unknown_name_lists_the_available_presets(self):
        with pytest.raises(ValueError, match="PVSystem"):
            resolve_etypes(["Bus", "Capacitor"])

    def test_a_dict_is_used_as_is(self):
        custom = {"Bus": {**PRESETS["Bus"], "min": 0.93}}

        assert resolve_etypes(custom)["Bus"]["min"] == 0.93

    def test_resolved_config_does_not_alias_the_presets(self):
        """Recalibrar um cenário não pode mudar o preset dos outros."""
        resolved = resolve_etypes(["Bus"])
        resolved["Bus"]["min"] = 0.5

        assert PRESETS["Bus"]["min"] == 0.90


class TestPresets:
    def test_every_preset_attribute_is_published_by_the_adapter(self):
        """Um nome de atributo errado deixaria o tipo inteiro cinza, sem erro."""
        for model, conf in PRESETS.items():
            assert set(conf["attrs"]) <= set(MODEL_SPECS[model].outputs), model

    def test_pv_is_in_per_unit_of_its_nameplate(self):
        pv = PRESETS["PVSystem"]

        assert pv["attrs"] == ["P1_pu", "P2_pu", "P3_pu"]
        assert (pv["min"], pv["max"]) == (0, 1.0)

    def test_default_hides_the_loads(self):
        assert "Load" not in DEFAULT_SHOW

    def test_default_hides_the_regulators(self):
        assert "RegControl" not in DEFAULT_SHOW


class FakeWebVis:
    """Registra o que ``attach_webvis`` pede ao webvis."""

    def __init__(self):
        self.config = {}
        self.etypes = None
        self.positions = None
        self.topology = SimpleNamespace(full_id="WebVis-0.topo")

    def set_config(self, **kwargs):
        self.config.update(kwargs)

    def set_etypes(self, etypes):
        self.etypes = etypes

    def Topology(self):
        return self.topology

    def set_node_positions(self, positions):
        self.positions = positions


def entity(eid, model_type):
    return SimpleNamespace(eid=eid, type=model_type, full_id=f"DSS-0.{eid}")


@pytest.fixture
def wired(monkeypatch):
    connected = []
    monkeypatch.setattr(
        "simulators.opendss.visualization.connect_many_to_one",
        lambda world, entities, dest, *attrs: connected.append(([e.eid for e in entities], attrs)),
    )
    grid = SimpleNamespace(
        children=[
            entity("Bus-650", "Bus"),
            entity("Load-671", "Load"),
            entity("RegControl-creg1", "RegControl"),
        ]
    )
    dss_sim = SimpleNamespace(get_bus_positions=lambda: {"Bus-650": (1.0, 2.0)})
    webvis = FakeWebVis()

    topology = attach_webvis(object(), dss_sim, grid, webvis)
    return webvis, connected, topology


class TestAttachWebvis:
    def test_lines_and_transformers_become_edges(self, wired):
        webvis, _, _ = wired

        assert webvis.config["merge_types"] == MERGE_TYPES

    def test_no_ignore_types_is_needed(self, wired):
        webvis, _, _ = wired

        assert "ignore_types" not in webvis.config

    def test_only_what_is_shown_is_connected(self, wired):
        """Carga e regulador existem no grid mas não estão no padrão; PV e Storage não existem."""
        _, connected, _ = wired

        assert connected == [(["Bus-650"], ("V1_pu", "V2_pu", "V3_pu"))]

    def test_bus_positions_are_keyed_by_full_id(self, wired):
        webvis, _, _ = wired

        assert webvis.positions == {"DSS-0.Bus-650": (1.0, 2.0)}

    def test_returns_the_topology(self, wired):
        webvis, _, topology = wired

        assert topology is webvis.topology
