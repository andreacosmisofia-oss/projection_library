"""Curve shapes for forward assumptions (``flows/06`` §4).

Three pilot shapes:

* ``flat`` — Y1 = Y2 = Y3, single anchor;
* ``linear_drift`` — anchors Y1 and Y3, Y2 interpolated;
* ``custom`` — three independent values (no transform here, the
  caller manages each year via PATCH).

The functions are pure: no DB, no registry. Routes call them and
persist the result.
"""

from __future__ import annotations

YEARS: tuple[str, ...] = ("Y1", "Y2", "Y3")


def apply_curve(
    curve_type: str,
    *,
    y1: float | None,
    y3: float | None,
    current: dict[str, float] | None = None,
) -> dict[str, float]:
    """Compute the Y1/Y2/Y3 values for a curve request.

    Parameters
    ----------
    curve_type
        ``flat`` | ``linear_drift`` | ``custom``.
    y1, y3
        Anchors. ``flat`` only needs ``y1``; ``linear_drift`` needs
        both; ``custom`` ignores both and falls back to ``current``.
    current
        Existing per-year values (used by ``custom`` to keep the
        triplet coherent if neither anchor is provided).
    """
    if curve_type == "flat":
        if y1 is None:
            raise ValueError("curve_type=flat requires y1")
        return {y: float(y1) for y in YEARS}
    if curve_type == "linear_drift":
        if y1 is None or y3 is None:
            raise ValueError("curve_type=linear_drift requires y1 and y3")
        y2 = (float(y1) + float(y3)) / 2.0
        return {"Y1": float(y1), "Y2": y2, "Y3": float(y3)}
    if curve_type == "custom":
        # ``custom`` doesn't impose a shape: we keep the existing
        # triplet (or zero-fill missing years) and let the user PATCH
        # individual years afterwards.
        existing = current or {}
        return {y: float(existing.get(y, 0.0)) for y in YEARS}
    raise ValueError(f"unknown curve_type: {curve_type!r}")


__all__ = ["YEARS", "apply_curve"]
