"""Sim properties feature: model, properties-CSV parsing, macro generation,
cache persistence, and version-banner capture (the Properties dialog's
backend; the dialog itself is a later pass)."""
import re
from pathlib import Path

from starpost.core.macro_generator import render_macro
from starpost.core.result_parser import parse_sim_output
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


CLASSIFICATION = {"residual_keywords": ["residual"], "force_keywords": ["force"]}


def test_parse_sim_output_reads_properties(tmp_path):
    (tmp_path / "caseA__properties.csv").write_text(
        "section,name,key,value\n"
        "sim,,units_system,SI\n"
        "solution,,iteration,4500\n"
        "solution,,initialized,true\n"
        "mesh,,cell_count,12400312\n"
        'region,Fluid,boundary_types,"Velocity Inlet=1; Wall=44"\n'
        "tag,baseline,,\n"
        "future_section,thing,key,value\n"
    )
    res = parse_sim_output(str(tmp_path / "caseA.sim"), tmp_path, CLASSIFICATION)
    props = res.properties
    assert props is not None
    assert props.get("sim").get("units_system") == "SI"
    # Consecutive same-(section, name) rows form one group, order preserved.
    assert props.get("solution").entries == [
        ("iteration", "4500"), ("initialized", "true"),
    ]
    # Quoted multi-valued cells survive intact.
    assert (props.get("region", "Fluid").get("boundary_types")
            == "Velocity Inlet=1; Wall=44")
    # A key-less row registers the group with no entries.
    assert props.get("tag", "baseline").entries == []
    # Unknown sections pass through — forward-compat with future macro tiers.
    assert props.get("future_section", "thing").get("key") == "value"


def test_parse_sim_output_no_properties_csv_is_none(tmp_path):
    # Older extractions simply have no properties CSV.
    res = parse_sim_output(str(tmp_path / "caseA.sim"), tmp_path, CLASSIFICATION)
    assert res.properties is None


def test_parse_properties_group_order_follows_the_file(tmp_path):
    (tmp_path / "caseA__properties.csv").write_text(
        "section,name,key,value\n"
        "solver,Segregated Flow,,\n"
        "solver,Segregated Energy,,\n"
        "mesh,,cell_count,100\n"
    )
    res = parse_sim_output(str(tmp_path / "caseA.sim"), tmp_path, CLASSIFICATION)
    assert [(g.section, g.name) for g in res.properties.groups] == [
        ("solver", "Segregated Flow"),
        ("solver", "Segregated Energy"),
        ("mesh", ""),
    ]


def test_parse_properties_empty_value_is_kept(tmp_path):
    # "not meshed": the macro writes mesh rows with empty values, which must
    # stay distinguishable from an absent section.
    (tmp_path / "caseA__properties.csv").write_text(
        "section,name,key,value\n"
        "mesh,,cell_count,\n"
    )
    res = parse_sim_output(str(tmp_path / "caseA.sim"), tmp_path, CLASSIFICATION)
    assert res.properties.get("mesh").get("cell_count") == ""
    assert res.properties.get("mesh").get("vertex_count") is None


def test_extract_macro_exports_properties(tmp_path):
    path = render_macro(Path("/out"), tmp_path)
    text = path.read_text()
    assert "exportProperties" in text
    assert "__properties.csv" in text
    assert "section,name,key,value" in text
    # Fragile packages are reached reflectively.
    assert 'Class.forName("star.meshing.MeshOperationManager")' in text
    assert '"star.common.TagManager"' in text
    assert '"star.meshing.BaseSize"' in text
    assert '"star.meshing.PartsTargetSurfaceSize"' in text
    assert '"star.meshing.PartsMinimumSurfaceSize"' in text
    assert '"star.prismmesher.NumPrismLayers"' in text
    # Getters only — nothing that computes or mutates.
    assert "initializeSolution" not in text
    assert "createSimulationSummary" not in text
    assert ".update(" not in text


def test_extract_macro_braces_balance(tmp_path):
    path = render_macro(Path("/out"), tmp_path)
    text = path.read_text()
    assert text.count("{") == text.count("}")


def test_extract_macro_no_compile_time_refs_outside_common(tmp_path):
    # A compile error kills the whole extraction, so fragile packages may
    # appear only inside string literals (Class.forName) or comments.
    text = render_macro(Path("/out"), tmp_path).read_text()
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)  # strip string literals
    text = re.sub(r"//[^\n]*", "", text)             # strip line comments
    for pkg in ("star.meshing", "star.cadmodeler", "star.prismmesher",
                "star.screenplay"):
        assert pkg not in text, f"compile-time reference to {pkg}"
