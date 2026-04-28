"""Assumption curve shapes (M8, ``flows/06_assumption_compilation.md`` §4).

Pilot v1.1 supports three temporal shapes for the Y1/Y2/Y3 triple of a
single ``(voice, method, assumption)``:

* ``flat`` — same value every year.
* ``linear_drift`` — ``Y2`` interpolated as the midpoint of ``Y1`` and
  ``Y3`` (50% progress; the spec keeps ``drift_progress`` exposable as
  a per-year assumption for the methods that need a non-linear ramp).
* ``custom`` — three explicit values, no interpolation.

Range validation is non-blocking: a value outside the heuristic range
returns ``"warning_range"`` so the UI can flag it, but the row is still
saved (the flow doc §3 calls this out explicitly — RP_xxx warnings,
not blocks).
"""

from __future__ import annotations

CURVE_FLAT = "flat"
CURVE_LINEAR_DRIFT = "linear_drift"
CURVE_CUSTOM = "custom"

CURVE_TYPES: frozenset[str] = frozenset(
    {CURVE_FLAT, CURVE_LINEAR_DRIFT, CURVE_CUSTOM}
)

VALIDATION_OK = "ok"
VALIDATION_WARNING_RANGE = "warning_range"

PROJECTION_YEARS: tuple[str, ...] = ("Y1", "Y2", "Y3")


class CurveError(ValueError):
    """Raised when the curve payload doesn't match its declared type."""


def apply_curve(
    curve_type: str,
    *,
    y1: float | None = None,
    y3: float | None = None,
    values: dict[str, float] | None = None,
) -> dict[str, float]:
    """Expand a curve specification into a ``{Y1, Y2, Y3}`` dict.

    The kwargs are deliberately permissive — the route layer accepts
    whichever subset matches ``curve_type`` and lets this function
    enforce the contract:

    * ``flat`` requires ``y1`` (the constant value).
    * ``linear_drift`` requires both ``y1`` and ``y3``; ``Y2`` is the
      midpoint.
    * ``custom`` requires ``values`` containing all three keys.
    """
    if curve_type == CURVE_FLAT:
        if y1 is None:
            raise CurveError("curve_type='flat' requires 'y1'")
        return {"Y1": y1, "Y2": y1, "Y3": y1}

    if curve_type == CURVE_LINEAR_DRIFT:
        if y1 is None or y3 is None:
            raise CurveError(
                "curve_type='linear_drift' requires both 'y1' and 'y3'"
            )
        return {"Y1": y1, "Y2": y1 + (y3 - y1) * 0.5, "Y3": y3}

    if curve_type == CURVE_CUSTOM:
        if not values or set(values) != set(PROJECTION_YEARS):
            raise CurveError(
                "curve_type='custom' requires 'values' with keys Y1, Y2, Y3"
            )
        return {year: float(values[year]) for year in PROJECTION_YEARS}

    raise CurveError(
        f"unknown curve_type '{curve_type}'; "
        f"expected one of {sorted(CURVE_TYPES)}"
    )


def validate_value_in_range(
    value: float,
    range_min: float | None,
    range_max: float | None,
) -> str:
    """Return ``"ok"`` or ``"warning_range"`` for a single value.

    Both bounds are optional: a missing bound simply skips the check on
    that side. When neither bound is set the return is ``"ok"`` — the
    UI shouldn't surface a warning icon for parameters whose plausible
    envelope we don't know.
    """
    if range_min is not None and value < range_min:
        return VALIDATION_WARNING_RANGE
    if range_max is not None and value > range_max:
        return VALIDATION_WARNING_RANGE
    return VALIDATION_OK


__all__ = [
    "CURVE_CUSTOM",
    "CURVE_FLAT",
    "CURVE_LINEAR_DRIFT",
    "CURVE_TYPES",
    "CurveError",
    "PROJECTION_YEARS",
    "VALIDATION_OK",
    "VALIDATION_WARNING_RANGE",
    "apply_curve",
    "validate_value_in_range",
]
