"""The convergence threshold table and its evidence provenance."""
from starpost.core.convergence.config import (
    THRESHOLD_PROVENANCE,
    TOLERANCE_PRESETS,
    ConvergenceConfig,
    MonitorConfig,
)
from starpost.core.convergence.models import Provenance, MetadataField


def test_defaults_match_the_published_threshold_table():
    """The [S]-tagged values are from the literature and must not drift: the
    ASME JFE editorial policy requires at least three decades of residual
    drop, and the iterative-error safety factor is 1.25."""
    c = ConvergenceConfig()
    assert c.d_min == 3.0
    assert c.d_min_advisory == 4.0
    assert c.d_min_turb == 2.0
    assert c.safety_factor == 1.25
    assert c.s_flat == 1e-4
    assert c.s_div == 1e-3
    assert c.s_div_window == 50
    assert c.s_div_min_r2 == 0.5
    assert c.kappa_div == 10.0
    assert c.eps_prec_double == 1e-13
    assert c.eps_prec_single == 1e-6
    assert c.window_min == 200
    assert c.window_fraction == 0.2
    assert c.gamma == 5.0
    assert c.lambda_ind == 20
    assert c.n_eff_min == 30.0
    assert c.n_eff_floor == 10.0
    assert c.tau0_over_n_warn == 0.05
    assert c.min_fit_points == 20
    assert c.rho_stagnant == 0.999
    assert c.mk_trend_z == 5.0
    assert c.mk_trend_departure_fraction == 0.25


def test_tolerance_presets():
    assert TOLERANCE_PRESETS["screening"] == 1e-3
    assert TOLERANCE_PRESETS["production"] == 5e-4


def test_every_threshold_carries_its_provenance():
    """A user asking 'where does this number come from?' must get an answer,
    so every configurable field is tagged [S] (sourced) or [D] (design)."""
    c = ConvergenceConfig()
    configurable = {
        f for f in c.__dataclass_fields__ if f not in ("monitors", "tolerance_fraction")
    }
    assert configurable <= set(THRESHOLD_PROVENANCE)
    assert set(THRESHOLD_PROVENANCE.values()) <= {"[S]", "[D]"}
    assert THRESHOLD_PROVENANCE["d_min"] == "[S]"
    assert THRESHOLD_PROVENANCE["safety_factor"] == "[S]"
    assert THRESHOLD_PROVENANCE["s_flat"] == "[D]"
    assert THRESHOLD_PROVENANCE["mk_trend_z"] == "[D]"
    assert THRESHOLD_PROVENANCE["mk_trend_departure_fraction"] == "[D]"


def test_monitor_config_defaults_to_non_primary_auto_scale():
    m = ConvergenceConfig().monitor("anything")
    assert m.is_primary is False
    assert m.tolerance_fraction is None
    assert m.reference_scale is None


def test_per_monitor_tolerance_overrides_the_global_one():
    c = ConvergenceConfig(
        tolerance_fraction=1e-3,
        monitors={"Drag": MonitorConfig(is_primary=True, tolerance_fraction=5e-4)},
    )
    assert c.tolerance_for("Drag") == 5e-4
    assert c.tolerance_for("Lift") == 1e-3


def test_metadata_field_known_only_when_a_value_was_resolved():
    assert MetadataField("steady", Provenance.DERIVED).known is True
    assert MetadataField(None, Provenance.ABSENT).known is False
    assert MetadataField("", Provenance.ABSENT).known is False
