"""Rebuild the Geometry > Parts tree from extracted sim properties.

The extraction macro writes two flat sections: ``part_tree`` (the top-level
entries of the Parts node, with type and leaf counts) and ``part`` (every
leaf part, with a ``path`` recording its composite ancestors). This module
turns those rows back into a nested tree for the Properties dialog — pure
data logic, no Qt, so it stays unit-testable headless.

Path format (STAR's own display convention, validated on a real install):
composite ancestors joined with ``.``, a single ``|`` before the leaf name
(``Original files.Chris Penny's car|wing front 5``); a top-level leaf's path
is just its name. Part names may legitimately contain ``.``, so ancestor
strings are matched against known top-level names longest-first before
falling back to splitting on ``.``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from starpost.data.models import SimProperties


@dataclass
class PartNode:
    """One entry of the Parts tree: a composite (has children / leaf_count)
    or a leaf part (has surface/curve counts)."""
    name: str
    type: str = ""
    leaf_count: Optional[int] = None   # composites: leaf parts contained
    surfaces: str = ""                 # leaves: counts as extracted ("" unknown)
    curves: str = ""
    children: list["PartNode"] = field(default_factory=list)


@dataclass
class PartsTree:
    roots: list[PartNode] = field(default_factory=list)
    truncated: int = 0                 # parts beyond the extraction cap

    @property
    def empty(self) -> bool:
        return not self.roots and not self.truncated


def build_parts_tree(props: Optional[SimProperties]) -> PartsTree:
    """The Parts tree for ``props``, alphabetically sorted at every level.
    Empty tree when there is no part data (pre-parts extraction)."""
    tree = PartsTree()
    if props is None:
        return tree

    roots: dict[str, PartNode] = {}

    def root(name: str) -> PartNode:
        node = roots.get(name)
        if node is None:
            node = PartNode(name=name)
            roots[name] = node
        return node

    # Two passes: all part_tree groups (the top-level roots) before any part
    # groups (leaves, attached via _ancestors' longest-first name matching
    # against those roots). The extraction macro happens to write part_tree
    # sections first, but this must not be an implicit cross-layer dependency
    # on file order — a hand-edited or reordered CSV must resolve identically.
    for g in props.groups:
        if g.section != "part_tree":
            continue
        if not g.name:
            tree.truncated += _count(g.get("truncated"))
            continue
        node = root(g.name)
        node.type = g.get("type") or node.type
        leaf_count = g.get("leaf_parts") or ""
        if leaf_count.isdigit():
            node.leaf_count = int(leaf_count)

    for g in props.groups:
        if g.section != "part":
            continue
        if not g.name:
            tree.truncated += _count(g.get("truncated"))
            continue
        _attach_leaf(g, root, roots)

    tree.roots = sorted(roots.values(), key=lambda n: n.name.casefold())
    for node in tree.roots:
        _sort_children(node)
    return tree


def _attach_leaf(g, root, roots: dict[str, PartNode]) -> None:
    """Place one ``part`` group under its composite ancestors (from ``path``)."""
    leaf = PartNode(
        name=g.name,
        type=g.get("type") or "",
        surfaces=g.get("surfaces") or "",
        curves=g.get("curves") or "",
    )
    ancestors = _ancestors(g.get("path") or "", g.name, roots)
    if not ancestors:
        # Top-level leaf: merge details onto its part_tree entry when one
        # exists (same entity), otherwise it becomes a root itself.
        existing = roots.get(leaf.name)
        if existing is None:
            roots[leaf.name] = leaf
        else:
            existing.type = leaf.type or existing.type
            existing.surfaces, existing.curves = leaf.surfaces, leaf.curves
        return
    node = root(ancestors[0])
    for name in ancestors[1:]:
        node = _child(node, name)
    _child_add(node, leaf)


def _ancestors(path: str, leaf_name: str, roots: dict[str, PartNode]) -> list[str]:
    """The composite chain above a leaf, resolved from its path string."""
    if path.endswith("|" + leaf_name):
        anc = path[: -(len(leaf_name) + 1)]
    elif "|" in path:
        anc = path.split("|", 1)[0]
    else:
        return []  # path == name (top-level) or absent/unparseable
    if not anc:
        return []
    # A known top-level name may itself contain "." — match longest-first
    # before splitting the remainder on ".".
    for name in sorted(roots, key=len, reverse=True):
        if anc == name:
            return [name]
        if anc.startswith(name + "."):
            rest = anc[len(name) + 1:]
            return [name] + [s for s in rest.split(".") if s]
    return [s for s in anc.split(".") if s]


def _child(node: PartNode, name: str) -> PartNode:
    for c in node.children:
        if c.name == name:
            return c
    c = PartNode(name=name)
    node.children.append(c)
    return c


def _child_add(node: PartNode, leaf: PartNode) -> None:
    for i, c in enumerate(node.children):
        if c.name == leaf.name and not c.children:
            node.children[i] = leaf
            return
    node.children.append(leaf)


def _sort_children(node: PartNode) -> None:
    node.children.sort(key=lambda n: n.name.casefold())
    for c in node.children:
        _sort_children(c)


def _count(value: Optional[str]) -> int:
    return int(value) if value and value.isdigit() else 0


def iter_part_names(tree: PartsTree) -> list[str]:
    """Every node name in the parts tree — composites and leaves — depth-first
    in tree (alphabetical) order. Empty list for a tree with no parts."""
    names: list[str] = []

    def walk(node: PartNode) -> None:
        names.append(node.name)
        for child in node.children:
            walk(child)

    for root in tree.roots:
        walk(root)
    return names


def matching_parts(tree: PartsTree, query: str) -> list[str]:
    """Part names containing ``query`` (case-insensitive substring). An empty
    or whitespace-only query returns every name."""
    q = query.strip().casefold()
    names = iter_part_names(tree)
    if not q:
        return names
    return [n for n in names if q in n.casefold()]
