"""Row builders for the Mesh / Regions / Physics properties tabs: pure
SimProperties -> Row transformations, no Qt. Fixtures echo the sections the
extraction macro writes (validated against a real sim)."""
from starpost.data.models import PropertyGroup, SimProperties
from starpost.data.prop_rows import (
    Row,
    build_mesh_rows,
    build_physics_rows,
    build_region_rows,
)


def _g(section, name, *entries):
    return PropertyGroup(section=section, name=name, entries=list(entries))


def _mesh_props() -> SimProperties:
    return SimProperties(groups=[
        _g("mesh", "", ("cell_count", "21737167"),
           ("interior_face_count", "65351479"), ("vertex_count", "23272181")),
        _g("mesh_op", "Surface Wrapper",
           ("type", "SurfaceWrapperAutoMeshOperation"),
           ("meshers", "Surface Wrapper"), ("base_size", "0.01 m")),
        _g("mesh_op", "Automated Mesh",
           ("type", "AutoMeshOperation"),
           ("meshers", "Surface Remesher; Trimmed Cell Mesher"),
           ("base_size", "24.0 mm"), ("prism_layers", "1")),
    ])


def test_mesh_counts_format_with_separators():
    rows = build_mesh_rows(_mesh_props())
    assert (rows[0].label, rows[0].value) == ("Cells", "21,737,167")
    assert (rows[1].label, rows[1].value) == ("Interior faces", "65,351,479")
    assert (rows[2].label, rows[2].value) == ("Vertices", "23,272,181")


def test_mesh_ops_keep_pipeline_order_with_detail_children():
    rows = build_mesh_rows(_mesh_props())
    ops = rows[3:]
    assert [(r.label, r.value) for r in ops] == [
        ("Surface Wrapper", "SurfaceWrapperAutoMeshOperation"),
        ("Automated Mesh", "AutoMeshOperation"),
    ]
    auto = ops[1]
    meshers = auto.children[0]
    assert meshers.label == "Meshers"
    assert [c.label for c in meshers.children] == [
        "Surface Remesher", "Trimmed Cell Mesher",
    ]
    assert ("Base size", "24.0 mm") in [(c.label, c.value) for c in auto.children]
    assert ("Prism layers", "1") in [(c.label, c.value) for c in auto.children]
    # Keys the extraction didn't produce are simply absent.
    assert "Target surface size" not in [c.label for c in auto.children]


def test_mesh_not_meshed_collapses_counts():
    props = SimProperties(groups=[
        _g("mesh", "", ("cell_count", ""), ("interior_face_count", ""),
           ("vertex_count", "")),
    ])
    rows = build_mesh_rows(props)
    assert [(r.label, r.value) for r in rows] == [("Volume mesh", "not meshed")]


def test_regions_sorted_with_boundary_breakdown():
    props = SimProperties(groups=[
        _g("region", "Radiator", ("type", "Porous Region"),
           ("continuum", "Physics 1"), ("boundaries", "8"),
           ("boundary_types", "Wall=4; Baffle Boundary=1")),
        _g("region", "External flow", ("type", "Fluid Region"),
           ("continuum", "Physics 1"), ("boundaries", "54"),
           ("boundary_types", "Symmetry Plane=3; Wall=43")),
        _g("interface", "", ("count", "2")),
        _g("interface", "Fan shroud"),
        _g("interface", "Fan downstream"),
    ])
    rows = build_region_rows(props)
    assert [(r.label, r.value) for r in rows] == [
        ("External flow", "Fluid Region"),
        ("Radiator", "Porous Region"),
        ("Interfaces", "2"),
    ]
    ext = rows[0]
    assert (ext.children[0].label, ext.children[0].value) == (
        "Continuum", "Physics 1",
    )
    boundaries = ext.children[1]
    assert (boundaries.label, boundaries.value) == ("Boundaries", "54")
    assert [(c.label, c.value) for c in boundaries.children] == [
        ("Symmetry Plane", "3"), ("Wall", "43"),
    ]
    # Interface names sort case-insensitively under the count row.
    assert [c.label for c in rows[2].children] == [
        "Fan downstream", "Fan shroud",
    ]


def test_physics_continua_solvers_and_criteria():
    props = SimProperties(groups=[
        _g("continuum", "Physics 1",
           ("models", "Three Dimensional; Gas; Turbulent"), ("regions", "3")),
        _g("solver", "Wall Distance"),
        _g("solver", "Coupled Implicit"),
        _g("criterion", "Maximum Steps", ("enabled", "true")),
        _g("criterion", "Stop File", ("enabled", "false")),
    ])
    rows = build_physics_rows(props)
    assert (rows[0].label, rows[0].value) == ("Physics 1", "3 regions")
    models = rows[0].children[0]
    assert (models.label, models.value) == ("Models", "3")
    assert [c.label for c in models.children] == [
        "Three Dimensional", "Gas", "Turbulent",
    ]
    solvers = rows[1]
    assert (solvers.label, solvers.value) == ("Solvers", "2")
    # Solver order is STAR's own — not sorted.
    assert [c.label for c in solvers.children] == [
        "Wall Distance", "Coupled Implicit",
    ]
    criteria = rows[2]
    assert (criteria.label, criteria.value) == ("Stopping criteria", "2")
    assert [(c.label, c.value) for c in criteria.children] == [
        ("Maximum Steps", "Enabled"), ("Stop File", "Disabled"),
    ]


def test_singular_region_count():
    props = SimProperties(groups=[
        _g("continuum", "Physics 1", ("models", "Gas"), ("regions", "1")),
    ])
    assert build_physics_rows(props)[0].value == "1 region"


def test_no_data_returns_empty():
    assert build_mesh_rows(None) == []
    assert build_region_rows(None) == []
    assert build_physics_rows(None) == []
    only_parts = SimProperties(groups=[_g("part", "wing", ("surfaces", "1"))])
    assert build_mesh_rows(only_parts) == []
    assert build_region_rows(only_parts) == []
    assert build_physics_rows(only_parts) == []


def test_boundary_type_with_equals_in_name():
    props = SimProperties(groups=[
        _g("region", "R", ("boundaries", "1"),
           ("boundary_types", "Weird=Type=2")),
    ])
    boundaries = build_region_rows(props)[0].children[0]
    assert [(c.label, c.value) for c in boundaries.children] == [
        ("Weird=Type", "2"),
    ]


def test_row_dataclass_defaults():
    r = Row("label")
    assert r.value == "" and r.children == []
