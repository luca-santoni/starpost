"""Row builders for the Properties dialog's Mesh / Regions / Physics tabs.

Each builder turns the flat extracted ``SimProperties`` sections into generic
``Row(label, value, children)`` entries for a two-column tree — pure data
logic, no Qt, mirroring how ``parts_tree`` feeds the Parts tab. An empty list
means "no data for this tab" (the GUI shows its re-extract hint).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from starpost.data.models import SimProperties


@dataclass
class Row:
    """One tree row: a label, an optional value, and child rows."""
    label: str
    value: str = ""
    children: list["Row"] = field(default_factory=list)


def _split_list(value: str) -> list[str]:
    """A ``; ``-joined extracted cell as its items, whitespace stripped."""
    return [s.strip() for s in value.split(";") if s.strip()]


def _fmt_count(value: str) -> str:
    """Thousands separators for numeric counts; anything else as-is."""
    return f"{int(value):,}" if value.isdigit() else value


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def build_mesh_rows(props: Optional[SimProperties]) -> list[Row]:
    """Mesh tab: cell/face/vertex counts, then the mesh-operation pipeline.
    Operations keep extraction order — it is the pipeline order."""
    if props is None:
        return []
    rows: list[Row] = []
    mesh = props.get("mesh")
    if mesh is not None:
        if (mesh.get("cell_count") or "") == "":
            # The macro writes empty values when the sim has no volume mesh.
            rows.append(Row("Volume mesh", "not meshed"))
        else:
            rows.append(Row("Cells", _fmt_count(mesh.get("cell_count") or "")))
            rows.append(
                Row("Interior faces",
                    _fmt_count(mesh.get("interior_face_count") or ""))
            )
            rows.append(
                Row("Vertices", _fmt_count(mesh.get("vertex_count") or ""))
            )
    for g in props.groups:
        if g.section != "mesh_op" or not g.name:
            continue
        op = Row(g.name, g.get("type") or "")
        meshers = g.get("meshers")
        if meshers:
            op.children.append(
                Row("Meshers", children=[Row(m) for m in _split_list(meshers)])
            )
        for key, label in (
            ("base_size", "Base size"),
            ("target_surface_size", "Target surface size"),
            ("min_surface_size", "Minimum surface size"),
            ("prism_layers", "Prism layers"),
        ):
            value = g.get(key)
            if value:
                op.children.append(Row(label, value))
        rows.append(op)
    return rows


def build_region_rows(props: Optional[SimProperties]) -> list[Row]:
    """Regions tab: one row per region (sorted) with its continuum and
    boundary-type breakdown, then the interfaces."""
    if props is None:
        return []
    rows: list[Row] = []
    regions = [g for g in props.groups if g.section == "region" and g.name]
    for g in sorted(regions, key=lambda g: g.name.casefold()):
        region = Row(g.name, g.get("type") or "")
        continuum = g.get("continuum")
        if continuum:
            region.children.append(Row("Continuum", continuum))
        boundaries = Row("Boundaries", g.get("boundaries") or "")
        for part in _split_list(g.get("boundary_types") or ""):
            # Split on the LAST "=": type names could contain "=", the
            # trailing count cannot.
            btype, _, count = part.rpartition("=")
            if btype:
                boundaries.children.append(Row(btype, count))
        if boundaries.value or boundaries.children:
            region.children.append(boundaries)
        rows.append(region)
    names = [g for g in props.groups if g.section == "interface" and g.name]
    head = props.get("interface")
    if names or head is not None:
        count = (head.get("count") if head else None) or str(len(names))
        rows.append(
            Row("Interfaces", count,
                children=[Row(g.name) for g in
                          sorted(names, key=lambda g: g.name.casefold())])
        )
    return rows


def build_physics_rows(props: Optional[SimProperties]) -> list[Row]:
    """Physics tab: continua (sorted) with their model lists, then solvers
    and stopping criteria in STAR's own order."""
    if props is None:
        return []
    rows: list[Row] = []
    continua = [g for g in props.groups if g.section == "continuum" and g.name]
    for g in sorted(continua, key=lambda g: g.name.casefold()):
        region_count = g.get("regions") or ""
        value = (
            _plural(int(region_count), "region")
            if region_count.isdigit() else region_count
        )
        continuum = Row(g.name, value)
        models = _split_list(g.get("models") or "")
        if models:
            continuum.children.append(
                Row("Models", str(len(models)),
                    children=[Row(m) for m in models])
            )
        rows.append(continuum)
    solvers = [g for g in props.groups if g.section == "solver" and g.name]
    if solvers:
        rows.append(
            Row("Solvers", str(len(solvers)),
                children=[Row(g.name) for g in solvers])
        )
    criteria = [g for g in props.groups if g.section == "criterion" and g.name]
    if criteria:
        states = {"true": "Enabled", "false": "Disabled"}
        rows.append(
            Row("Stopping criteria", str(len(criteria)),
                children=[
                    Row(g.name,
                        states.get((g.get("enabled") or "").lower(),
                                   g.get("enabled") or ""))
                    for g in criteria
                ])
        )
    return rows
