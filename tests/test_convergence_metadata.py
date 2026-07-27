"""Resolving run metadata from cached sim properties, with provenance.

The rule under test throughout: extracted beats derived beats absent, and an
absent field is never guessed."""
from starpost.core.convergence.metadata import read_metadata
from starpost.core.convergence.models import Provenance
from starpost.data.models import PropertyGroup, SimProperties


def props(*groups: PropertyGroup) -> SimProperties:
    return SimProperties(groups=list(groups))


def test_no_properties_at_all_gives_everything_absent():
    """Imported portable CSVs carry no properties. Every field must come back
    absent rather than defaulted, so the verdict degrades honestly."""
    m = read_metadata(None)
    for f in (m.solver_regime, m.solver_type, m.precision, m.residual_normalization):
        assert f.provenance is Provenance.ABSENT
        assert f.known is False


def test_regime_and_solver_type_derived_from_the_continuum_model_list():
    """The enabled-models list already names Steady/Implicit Unsteady and
    Segregated/Coupled, so these are derivable without a macro change."""
    m = read_metadata(props(PropertyGroup(
        section="continuum", name="Physics 1",
        entries=[("models", "Steady; Gas; Segregated Flow; K-Epsilon Turbulence")],
    )))
    assert m.solver_regime.value == "steady"
    assert m.solver_regime.provenance is Provenance.DERIVED
    assert m.solver_type.value == "segregated"
    assert m.solver_type.provenance is Provenance.DERIVED
    assert m.is_unsteady is False


def test_implicit_unsteady_is_recognised_and_flagged_unsteady():
    m = read_metadata(props(PropertyGroup(
        section="continuum", name="Physics 1",
        entries=[("models", "Implicit Unsteady; Liquid; Coupled Flow")],
    )))
    assert m.solver_regime.value == "implicit_unsteady"
    assert m.solver_type.value == "coupled"
    assert m.is_unsteady is True
    assert m.is_steady is False


# --- I5: is_steady must positively recognise steady, not default to it -----

def test_is_steady_is_true_only_for_the_literal_steady_token():
    m = read_metadata(props(PropertyGroup(
        section="continuum", name="Physics 1",
        entries=[("models", "Steady; Segregated Flow")],
    )))
    assert m.is_steady is True


def test_is_steady_is_false_for_harmonic_balance_even_though_is_unsteady_misses_it():
    """The bug this closes: 'harmonic_balance' does not end with 'unsteady',
    so the old is_unsteady-based gate silently ran the steady tests on it."""
    m = read_metadata(props(PropertyGroup(
        section="continuum", name="Physics 1",
        entries=[("models", "Harmonic Balance; Coupled Flow")],
    )))
    assert m.solver_regime.value == "harmonic_balance"
    assert m.is_unsteady is False       # the trap: does not end with "unsteady"
    assert m.is_steady is False         # but must still be refused


def test_is_steady_is_false_when_the_regime_is_absent():
    """An absent regime must not default to steady."""
    m = read_metadata(None)
    assert m.solver_regime.known is False
    assert m.is_steady is False


def test_extracted_convergence_section_beats_derivation():
    """When the macro supplied the values directly, they win and are marked
    extracted — the derived route is only a fallback."""
    m = read_metadata(props(
        PropertyGroup(section="continuum", name="Physics 1",
                      entries=[("models", "Steady; Segregated Flow")]),
        PropertyGroup(section="convergence", name="", entries=[
            ("solver_regime", "implicit_unsteady"),
            ("solver_type", "coupled"),
            ("precision", "double"),
            ("residual_normalization", "auto"),
            ("auto_norm_sample_count", "5"),
        ]),
    ))
    assert m.solver_regime.value == "implicit_unsteady"
    assert m.solver_regime.provenance is Provenance.EXTRACTED
    assert m.precision.value == "double"
    assert m.precision.provenance is Provenance.EXTRACTED
    assert m.residual_normalization.value == "auto"
    assert m.auto_norm_sample_count == 5


def test_precision_is_never_derived():
    """Nothing already in the properties CSV implies build precision, so it
    stays absent until the macro supplies it."""
    m = read_metadata(props(PropertyGroup(
        section="continuum", name="Physics 1", entries=[("models", "Steady")],
    )))
    assert m.precision.provenance is Provenance.ABSENT


def test_empty_extracted_value_counts_as_absent():
    """The macro writes an empty value for 'read succeeded, nothing to report';
    that must not masquerade as a known value."""
    m = read_metadata(props(PropertyGroup(
        section="convergence", name="", entries=[("precision", "")],
    )))
    assert m.precision.known is False
    assert m.precision.provenance is Provenance.ABSENT


def test_cell_count_and_iteration_are_read_as_integers():
    m = read_metadata(props(
        PropertyGroup(section="mesh", name="", entries=[("cell_count", "1234567")]),
        PropertyGroup(section="solution", name="", entries=[("iteration", "4200")]),
    ))
    assert m.cell_count == 1234567
    assert m.n_iterations == 4200


def test_unparseable_numbers_do_not_raise():
    m = read_metadata(props(
        PropertyGroup(section="mesh", name="", entries=[("cell_count", "")]),
        PropertyGroup(section="solution", name="", entries=[("iteration", "n/a")]),
    ))
    assert m.cell_count is None
    assert m.n_iterations is None


def test_auto_norm_sample_count_defaults_to_the_star_ccm_default():
    assert read_metadata(None).auto_norm_sample_count == 5
