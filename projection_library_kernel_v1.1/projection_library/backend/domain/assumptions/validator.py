"""Runtime classification of assumption values (``flows/06`` §3).

Only the range check (RP_xxx in spirit) is implemented in the pilot:
each value is compared against the method's ``validation_range`` and
flagged ``warning_range`` if outside. The continuity check
(``warning_continuity``, CP_002-008) is left as ``ok`` until a
dedicated rule engine lands — see audit §12.

Pure function, no DB.
"""

from __future__ import annotations

from typing import Iterable, Literal

ValidationStatus = Literal["ok", "warning_range", "warning_continuity"]


def classify_value(
    value: float, validation_range: list[float] | None
) -> ValidationStatus:
    """Return ``warning_range`` if the value is outside the range, else ``ok``.

    ``validation_range`` is the registry's ``[min, max]`` pair (already
    persisted on the assumption row); ``None`` means "no range
    declared", which is treated as ``ok`` — the user owns the value.
    """
    if validation_range is None:
        return "ok"
    if len(validation_range) != 2:
        return "ok"
    low, high = validation_range
    if value < low or value > high:
        return "warning_range"
    return "ok"


def classify_triplet(
    values: Iterable[float], validation_range: list[float] | None
) -> ValidationStatus:
    """Return the worst classification across Y1/Y2/Y3."""
    statuses = [classify_value(v, validation_range) for v in values]
    if "warning_range" in statuses:
        return "warning_range"
    if "warning_continuity" in statuses:
        return "warning_continuity"
    return "ok"


__all__ = ["ValidationStatus", "classify_triplet", "classify_value"]
