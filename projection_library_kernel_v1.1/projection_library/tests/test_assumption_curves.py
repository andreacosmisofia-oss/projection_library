"""Unit tests for ``backend.domain.assumptions.curves``."""

from __future__ import annotations

import pytest

from backend.domain.assumptions.curves import (
    CurveError,
    apply_curve,
    validate_value_in_range,
)


def test_apply_curve_flat():
    out = apply_curve("flat", y1=0.10)
    assert out == {"Y1": 0.10, "Y2": 0.10, "Y3": 0.10}


def test_apply_curve_flat_requires_y1():
    with pytest.raises(CurveError):
        apply_curve("flat")


def test_apply_curve_linear_drift_midpoint():
    out = apply_curve("linear_drift", y1=0.10, y3=0.04)
    assert out["Y1"] == pytest.approx(0.10)
    assert out["Y3"] == pytest.approx(0.04)
    # Y2 = midpoint between Y1 and Y3.
    assert out["Y2"] == pytest.approx(0.07)


def test_apply_curve_linear_drift_requires_both_endpoints():
    with pytest.raises(CurveError):
        apply_curve("linear_drift", y1=0.10)
    with pytest.raises(CurveError):
        apply_curve("linear_drift", y3=0.04)


def test_apply_curve_custom_passthrough():
    out = apply_curve("custom", values={"Y1": 0.1, "Y2": 0.2, "Y3": 0.05})
    assert out == {"Y1": 0.1, "Y2": 0.2, "Y3": 0.05}


def test_apply_curve_custom_requires_full_triple():
    with pytest.raises(CurveError):
        apply_curve("custom", values={"Y1": 0.1, "Y2": 0.2})
    with pytest.raises(CurveError):
        apply_curve("custom", values={"Y1": 0.1, "Y2": 0.2, "Y4": 0.0})


def test_apply_curve_unknown_type_raises():
    with pytest.raises(CurveError):
        apply_curve("exponential", y1=0.1)


def test_validate_value_in_range_ok_inside():
    assert validate_value_in_range(0.10, 0.0, 1.0) == "ok"


def test_validate_value_in_range_warning_outside():
    assert validate_value_in_range(2.5, 0.0, 1.0) == "warning_range"
    assert validate_value_in_range(-0.1, 0.0, 1.0) == "warning_range"


def test_validate_value_in_range_handles_one_sided_bounds():
    assert validate_value_in_range(-100.0, None, 1.0) == "ok"
    assert validate_value_in_range(2.0, None, 1.0) == "warning_range"
    assert validate_value_in_range(2.0, 0.0, None) == "ok"
    assert validate_value_in_range(-1.0, 0.0, None) == "warning_range"


def test_validate_value_in_range_returns_ok_when_no_bounds():
    # No range → no warning, regardless of value.
    assert validate_value_in_range(1e9, None, None) == "ok"
