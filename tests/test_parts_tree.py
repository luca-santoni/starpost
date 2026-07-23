"""Parts-tree builder: SimProperties part/part_tree groups -> a nested,
alphabetically sorted tree matching STAR-CCM+'s Geometry > Parts display.
Fixtures use the real path format observed on the 2506 install."""
from starpost.data.models import PropertyGroup, SimProperties
from starpost.data.parts_tree import (
    build_parts_tree,
    iter_part_names,
    matching_parts,
)


def _g(section, name, *entries):
    return PropertyGroup(section=section, name=name, entries=list(entries))


def _props() -> SimProperties:
    return SimProperties(groups=[
        # part_tree: top-level entries, deliberately NOT alphabetical.
        _g("part_tree", "Original files",
           ("type", "CompositePart"), ("leaf_parts", "46")),
        _g("part_tree", "Tires",
           ("type", "SolidModelCompositePart"), ("leaf_parts", "2")),
        _g("part_tree", "SDM25-Body-CFD-12",
           ("type", "SolidModelPart"), ("leaf_parts", "1")),
        # Nested leaf: ancestors joined with ".", "|" before the leaf name.
        _g("part", "wing front 5",
           ("type", "SolidModelPart"),
           ("path", "Original files.Chris Penny's car|wing front 5"),
           ("surfaces", "2"), ("curves", "1")),
        _g("part", "Front tire",
           ("type", "SolidModelPart"),
           ("path", "Tires|Front tire"),
           ("surfaces", "1"), ("curves", "1")),
        # Top-level leaf: path == name, merges into its part_tree entry.
        _g("part", "SDM25-Body-CFD-12",
           ("type", "SolidModelPart"),
           ("path", "SDM25-Body-CFD-12"),
           ("surfaces", "5"), ("curves", "2")),
    ])


def test_roots_come_from_part_tree_and_sort_alphabetically():
    tree = build_parts_tree(_props())
    assert [n.name for n in tree.roots] == [
        "Original files", "SDM25-Body-CFD-12", "Tires",
    ]
    assert tree.roots[0].type == "CompositePart"
    assert tree.roots[0].leaf_count == 46
    assert not tree.empty and tree.truncated == 0


def test_nested_leaf_lands_under_intermediate_composite():
    tree = build_parts_tree(_props())
    orig = tree.roots[0]
    assert [c.name for c in orig.children] == ["Chris Penny's car"]
    car = orig.children[0]
    assert [c.name for c in car.children] == ["wing front 5"]
    leaf = car.children[0]
    assert leaf.type == "SolidModelPart"
    assert leaf.surfaces == "2" and leaf.curves == "1"
    assert leaf.children == []


def test_top_level_leaf_merges_with_its_part_tree_entry():
    tree = build_parts_tree(_props())
    body = next(n for n in tree.roots if n.name == "SDM25-Body-CFD-12")
    # One node, not a duplicate child: details merged onto the root entry.
    assert body.surfaces == "5" and body.curves == "2"
    assert body.children == []


def test_children_sort_alphabetically():
    props = _props()
    props.groups.append(_g("part", "Aero wing",
                           ("path", "Original files.Chris Penny's car|Aero wing")))
    tree = build_parts_tree(props)
    car = tree.roots[0].children[0]
    assert [c.name for c in car.children] == ["Aero wing", "wing front 5"]


def test_ancestor_matching_prefers_longest_top_level_name():
    # A top-level name containing "." must not be split apart.
    props = SimProperties(groups=[
        _g("part_tree", "v2.5 model", ("type", "CompositePart")),
        _g("part", "hull", ("path", "v2.5 model|hull")),
    ])
    tree = build_parts_tree(props)
    assert [n.name for n in tree.roots] == ["v2.5 model"]
    assert [c.name for c in tree.roots[0].children] == ["hull"]


def test_part_row_order_does_not_matter():
    # part rows may precede part_tree rows (e.g. a hand-edited portable CSV);
    # dotted top-level names must still resolve via longest-first matching.
    props = SimProperties(groups=[
        _g("part", "hull", ("path", "v2.5 model|hull")),
        _g("part_tree", "v2.5 model", ("type", "CompositePart")),
    ])
    tree = build_parts_tree(props)
    assert [n.name for n in tree.roots] == ["v2.5 model"]
    assert [c.name for c in tree.roots[0].children] == ["hull"]


def test_leaf_name_containing_pipe_resolves():
    props = SimProperties(groups=[
        _g("part", "a|b", ("path", "Assy|a|b"), ("surfaces", "1")),
    ])
    tree = build_parts_tree(props)
    assert [n.name for n in tree.roots] == ["Assy"]
    assert [c.name for c in tree.roots[0].children] == ["a|b"]


def test_leaf_with_unknown_root_creates_it():
    # part_tree section missing (older/failed section): tree still builds.
    props = SimProperties(groups=[
        _g("part", "wing", ("path", "Imported.Sub|wing"), ("surfaces", "3")),
    ])
    tree = build_parts_tree(props)
    assert [n.name for n in tree.roots] == ["Imported"]
    assert [c.name for c in tree.roots[0].children] == ["Sub"]
    assert tree.roots[0].children[0].children[0].name == "wing"


def test_pathless_leaf_becomes_a_root():
    # Extractions from before the path key existed degrade to a flat list.
    props = SimProperties(groups=[
        _g("part", "wing", ("type", "CadPart"), ("surfaces", "3")),
    ])
    tree = build_parts_tree(props)
    assert [n.name for n in tree.roots] == ["wing"]
    assert tree.roots[0].surfaces == "3"


def test_truncated_rows_are_summed():
    props = _props()
    props.groups.append(_g("part_tree", "", ("truncated", "3")))
    props.groups.append(_g("part", "", ("truncated", "40")))
    assert build_parts_tree(props).truncated == 43


def test_no_properties_or_no_part_data_is_empty():
    assert build_parts_tree(None).empty
    assert build_parts_tree(SimProperties()).empty
    only_mesh = SimProperties(groups=[_g("mesh", "", ("cell_count", "5"))])
    assert build_parts_tree(only_mesh).empty


def test_iter_part_names_includes_composites_and_leaves():
    names = iter_part_names(build_parts_tree(_props()))
    # Composites (roots) and their leaves are all present.
    assert "Tires" in names            # composite
    assert "Front tire" in names       # nested leaf
    assert "wing front 5" in names     # nested leaf
    assert "SDM25-Body-CFD-12" in names  # top-level leaf/root


def test_matching_parts_is_case_insensitive_substring():
    tree = build_parts_tree(_props())
    assert matching_parts(tree, "tire") == ["Tires", "Front tire"]
    assert matching_parts(tree, "TIRE") == ["Tires", "Front tire"]


def test_matching_parts_empty_query_returns_all():
    tree = build_parts_tree(_props())
    assert matching_parts(tree, "") == iter_part_names(tree)
    assert matching_parts(tree, "   ") == iter_part_names(tree)


def test_matching_parts_no_part_data_is_empty():
    empty = build_parts_tree(None)
    assert iter_part_names(empty) == []
    assert matching_parts(empty, "tire") == []
