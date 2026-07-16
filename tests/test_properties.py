"""Sim properties feature: model, properties-CSV parsing, macro generation,
cache persistence, and version-banner capture (the Properties dialog's
backend; the dialog itself is a later pass)."""
from starpost.data.models import (
    PropertyGroup,
    Report,
    SimProperties,
    SimResult,
)


def test_property_group_key_lookup():
    g = PropertyGroup(
        section="region", name="Fluid",
        entries=[("boundaries", "46"), ("continuum", "Physics 1")],
    )
    assert g.get("boundaries") == "46"
    assert g.get("continuum") == "Physics 1"
    assert g.get("missing") is None


def test_sim_properties_group_lookup():
    props = SimProperties(groups=[
        PropertyGroup(section="sim", entries=[("units_system", "SI")]),
        PropertyGroup(section="region", name="Fluid",
                      entries=[("boundaries", "46")]),
    ])
    assert props.get("sim").get("units_system") == "SI"
    assert props.get("region", "Fluid").get("boundaries") == "46"
    # Name must match exactly; sim-wide sections use the default "".
    assert props.get("region") is None
    assert props.get("nope") is None


def test_sim_result_signature_ignores_properties():
    # Differing properties must never push a batch out of comparison mode.
    a = SimResult(sim_path="/c/a.sim", reports=[Report(name="Drag", value=1.0)])
    b = SimResult(
        sim_path="/c/b.sim",
        reports=[Report(name="Drag", value=2.0)],
        properties=SimProperties(groups=[PropertyGroup(section="sim")]),
    )
    assert a.signature() == b.signature()
