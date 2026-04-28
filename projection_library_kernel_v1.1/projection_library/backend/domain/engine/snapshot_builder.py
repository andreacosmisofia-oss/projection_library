"""Build the persisted snapshot payload from a post-run ``ModelState``.

M10 (``flows/08_output_presentation.md``). The executor returns a
:class:`ProjectionResult` plus a ``final_state``; the route layer turns
those into one ``snapshots`` row + N ``snapshot_values`` rows. The
helpers here are pure functions over state — no DB, no FastAPI imports
— so they can be unit-tested in isolation and reused by the override
re-run trigger in M11.

Year semantics mirror :func:`backend.domain.engine.value_resolver.resolve_voice_value`:

* Historical years (``Y0`` and earlier) carry the actual from
  ``state.historical_data``; ``base_value`` is ``None`` (no engine
  output exists for the past) and ``override_delta`` is ``0.0`` (the
  override layer only applies to projection years).
* Projection years (``Y1``..``Y3``) carry ``base_value`` from
  ``state.base_values`` and ``override_delta`` as the sum of active
  overrides on the pair; ``value`` is their composition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.domain.engine.value_resolver import ModelState


_YEAR_RE = re.compile(r"^Y(-?\d+)$")

_SEVERITIES: tuple[str, ...] = ("block", "error", "warning", "info")


@dataclass(frozen=True)
class SnapshotValueRow:
    """Pure-data row materialised by the route into ``SnapshotValue``."""

    voice_id: str
    year: str
    value: float | None
    base_value: float | None
    override_delta: float


def _is_projection_year(year: str) -> bool:
    match = _YEAR_RE.match(year)
    return match is not None and int(match.group(1)) >= 1


def _year_sort_key(year: str) -> tuple[int, int]:
    match = _YEAR_RE.match(year)
    if match:
        return (0, int(match.group(1)))
    return (1, 0)


def _sum_active_override_delta(
    state: ModelState, voice_id: str, year: str
) -> float:
    return sum(
        ov.delta_amount
        for ov in state.overrides
        if ov.is_active and ov.voice_id == voice_id and ov.year == year
    )


def build_snapshot_values(state: ModelState) -> list[SnapshotValueRow]:
    """Flatten ``state`` into one row per ``(voice_id, year)``.

    Covers the union of voices observed in ``historical_data`` and
    ``base_values``; for each voice, emits a row per year present in
    that voice's slot (historical or projection). Sorted by ``voice_id``
    then year for deterministic output (tests + dashboards depend on a
    stable ordering).
    """
    voice_ids = sorted(
        set(state.historical_data) | set(state.base_values)
    )
    rows: list[SnapshotValueRow] = []
    for voice_id in voice_ids:
        hist = state.historical_data.get(voice_id, {})
        proj = state.base_values.get(voice_id, {})
        years = sorted(set(hist) | set(proj), key=_year_sort_key)
        for year in years:
            if _is_projection_year(year):
                base = proj.get(year)
                delta = _sum_active_override_delta(state, voice_id, year)
                value = (base if base is not None else 0.0) + delta
                rows.append(
                    SnapshotValueRow(
                        voice_id=voice_id,
                        year=year,
                        value=value,
                        base_value=base,
                        override_delta=delta,
                    )
                )
            else:
                value = hist.get(year)
                rows.append(
                    SnapshotValueRow(
                        voice_id=voice_id,
                        year=year,
                        value=value,
                        base_value=None,
                        override_delta=0.0,
                    )
                )
    return rows


def build_validation_summary(state: ModelState) -> dict[str, int]:
    """Return per-severity counts (always includes the four canonical keys)."""
    summary: dict[str, int] = {sev: 0 for sev in _SEVERITIES}
    for issue in state.validation_issues:
        summary[issue.severity] = summary.get(issue.severity, 0) + 1
    return summary


def serialise_validation_issues(state: ModelState) -> list[dict]:
    """Serialise engine ``ValidationIssue`` instances to JSON-ready dicts."""
    return [
        {
            "rule_id": issue.rule_id,
            "severity": issue.severity,
            "message": issue.message,
            "voice_id": issue.voice_id,
            "year": issue.year,
            "context": dict(issue.context) if issue.context else {},
        }
        for issue in state.validation_issues
    ]


__all__ = [
    "SnapshotValueRow",
    "build_snapshot_values",
    "build_validation_summary",
    "serialise_validation_issues",
]
