"""Resolve run metadata from cached sim properties.

Convergence conclusions are invalid without certain metadata, and the theory
specification is explicit that it must be captured rather than guessed. So each
field records where its value came from:

    extracted  the macro's `convergence` properties section supplied it
    derived    inferred from data already in the properties CSV
    absent     unavailable — the dependent verdict is suppressed, not guessed

The precision field is deliberately never derived. Nothing already extracted
implies the build precision, and defaulting it to double would permanently
misclassify every single-precision run as STALLED.
"""
from __future__ import annotations

from typing import Optional

from starpost.core.convergence.models import MetadataField, Provenance, RunMetadata
from starpost.data.models import SimProperties

_ABSENT = MetadataField(None, Provenance.ABSENT)

# Longest first: "implicit unsteady" must win over a bare "unsteady".
_REGIME_KEYWORDS = (
    ("harmonic balance", "harmonic_balance"),
    ("implicit unsteady", "implicit_unsteady"),
    ("explicit unsteady", "explicit_unsteady"),
    ("steady", "steady"),
)
_SOLVER_TYPE_KEYWORDS = (
    ("coupled", "coupled"),
    ("segregated", "segregated"),
)


def _extracted(props: Optional[SimProperties], key: str) -> Optional[str]:
    """Look up a key in the macro's `convergence` section. An empty value means
    'read succeeded, nothing to report' and counts as absent."""
    if props is None:
        return None
    group = props.get("convergence")
    if group is None:
        return None
    value = group.get(key)
    return value.strip() if value and value.strip() else None


def _field(props: Optional[SimProperties], key: str,
           derived: Optional[str] = None) -> MetadataField:
    value = _extracted(props, key)
    if value:
        return MetadataField(value, Provenance.EXTRACTED)
    if derived:
        return MetadataField(derived, Provenance.DERIVED)
    return _ABSENT


def _model_text(props: Optional[SimProperties]) -> str:
    """Every continuum's enabled-models list, lowercased and concatenated."""
    if props is None:
        return ""
    parts = [
        value
        for group in props.groups
        if group.section == "continuum"
        for key, value in group.entries
        if key == "models"
    ]
    return " ; ".join(parts).lower()


def _match(text: str, keywords: tuple[tuple[str, str], ...]) -> Optional[str]:
    for needle, result in keywords:
        if needle in text:
            return result
    return None


def _int(props: Optional[SimProperties], section: str, key: str) -> Optional[int]:
    if props is None:
        return None
    group = props.get(section)
    if group is None:
        return None
    raw = group.get(key)
    if not raw:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def read_metadata(props: Optional[SimProperties]) -> RunMetadata:
    """Build a RunMetadata from cached sim properties.

    Regime and solver type fall back to the continuum model list, which names
    "Steady"/"Implicit Unsteady" and "Segregated Flow"/"Coupled Flow" — reliable
    enough to branch the whole analysis on."""
    models = _model_text(props)
    sample_count = _extracted(props, "auto_norm_sample_count")
    try:
        auto_norm = int(sample_count) if sample_count else 5
    except ValueError:
        auto_norm = 5
    return RunMetadata(
        solver_regime=_field(props, "solver_regime", _match(models, _REGIME_KEYWORDS)),
        solver_type=_field(props, "solver_type", _match(models, _SOLVER_TYPE_KEYWORDS)),
        precision=_field(props, "precision"),
        residual_normalization=_field(props, "residual_normalization"),
        auto_norm_sample_count=auto_norm,
        cell_count=_int(props, "mesh", "cell_count"),
        n_iterations=_int(props, "solution", "iteration"),
    )
