import pytest

from starpost.core import units as u


def test_default_is_a_no_op():
    assert u.convert_value(12.0, "N", "default") == (12.0, "N")


def test_force_si_to_imperial():
    val, unit = u.convert_value(100.0, "N", "imperial")
    assert unit == "lbf"
    assert val == pytest.approx(22.4808943, rel=1e-6)


def test_force_imperial_unit_to_si():
    val, unit = u.convert_value(10.0, "lbf", "si")
    assert unit == "N"
    assert val == pytest.approx(44.48221615, rel=1e-6)


def test_pressure_pa_to_psi():
    val, unit = u.convert_value(6894.757293168, "Pa", "imperial")
    assert unit == "psi"
    assert val == pytest.approx(1.0, rel=1e-9)


def test_velocity_ms_to_fts():
    val, unit = u.convert_value(1.0, "m/s", "imperial")
    assert unit == "ft/s"
    assert val == pytest.approx(3.280839895, rel=1e-6)


def test_temperature_kelvin_to_fahrenheit_affine():
    val, unit = u.convert_value(300.0, "K", "imperial")
    assert unit == "degF"
    assert val == pytest.approx(80.33, abs=1e-2)


def test_temperature_round_trip_back_to_kelvin():
    f_val, _ = u.convert_value(300.0, "K", "imperial")   # -> degF
    k_val, unit = u.convert_value(f_val, "degF", "si")   # -> K
    assert unit == "K"
    assert k_val == pytest.approx(300.0, abs=1e-6)


def test_compound_moment_unit():
    val, unit = u.convert_value(1.35581794833, "N-m", "imperial")
    assert unit == "lbf-ft"
    assert val == pytest.approx(1.0, rel=1e-6)


def test_unknown_unit_passes_through():
    assert u.convert_value(5.0, "widgets", "si") == (5.0, "widgets")


def test_dimensionless_and_blank_pass_through():
    assert u.convert_value(0.42, "", "imperial") == (0.42, "")
    assert u.convert_value(0.42, "Cd", "imperial") == (0.42, "Cd")


def test_already_in_target_unit_is_identity():
    assert u.convert_value(50.0, "N", "si") == (50.0, "N")


def test_none_value_keeps_shape_and_reports_target_unit():
    val, unit = u.convert_value(None, "N", "imperial")
    assert val is None
    assert unit == "lbf"


def test_convert_series_scales_every_point():
    ys, unit = u.convert_series([0.0, 100.0], "N", "imperial")
    assert unit == "lbf"
    assert ys[0] == pytest.approx(0.0)
    assert ys[1] == pytest.approx(22.4808943, rel=1e-6)


def test_target_unit_only():
    assert u.target_unit("Pa", "imperial") == "psi"
    assert u.target_unit("Pa", "default") == "Pa"
    assert u.target_unit("widgets", "si") == "widgets"


def test_quantity_for_unit():
    assert u.quantity_for_unit("lbf") == "Force"
    assert u.quantity_for_unit("widgets") == ""


def test_normalize_system_coerces_bad_values():
    assert u.normalize_system("SI") == "si"
    assert u.normalize_system("nonsense") == "default"
    assert u.normalize_system(None) == "default"
