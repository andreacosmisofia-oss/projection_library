"""Assumption pre-population (``flows/06_assumption_compilation.md`` §2).

Walks every ``method_configs`` row of a project, extracts the
parameter names referenced by the chosen method's ``formula_python``,
and seeds ``assumptions`` rows for Y1/Y2/Y3.

Default values come from the ``historical_kpis`` AGG row
(``default_for_projection``) when the method declares a
``default_kpi_example`` template that resolves for the voice;
otherwise the row is written with ``source='fallback'`` and value 0.

Re-running is idempotent: rows whose ``source`` is ``user_input``
survive untouched (the repo's ``bulk_upsert_defaults`` guarantees it).
On every run we also drop ``(voice, method)`` pairs that no longer
exist in ``method_configs`` — the user may have switched method on a
voice between runs (TC-06-04).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from backend.infrastructure.db.models import HistoricalKPI, MethodConfig
from backend.infrastructure.db.repositories.assumptions_repo import (
    bulk_upsert_defaults,
    delete_orphan_pairs,
    list_assumptions,
)
from backend.infrastructure.registry import Registries

YEARS: tuple[str, ...] = ("Y1", "Y2", "Y3")

# Captures every distinct ``assumptions[voice]['<name>']`` reference in
# ``formula_python``. The grammar is loose on purpose: methods
# occasionally use ``\"name\"`` instead of ``'name'`` and the
# whitespace inside the brackets is inconsistent.
_ASSUMPTION_NAME_RE = re.compile(
    r"""assumptions\[\s*voice\s*\]\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\]"""
)


@dataclass
class PopulateReport:
    """Counters returned by the route (matches the flow §"API" example)."""

    populated: int = 0
    kpi_default_used: int = 0
    fallback_used: int = 0
    user_input_preserved: int = 0
    pairs_deleted: int = 0
    methods_skipped: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_assumption_names(formula_python: str | None) -> list[str]:
    """Return the unique assumption names referenced in a method formula."""
    if not formula_python:
        return []
    seen: list[str] = []
    for match in _ASSUMPTION_NAME_RE.finditer(formula_python):
        name = match.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def _resolve_default_kpi_id(
    template: str | None, voice_id: str
) -> str | None:
    """Substitute ``<voice>`` in the registry template.

    The registry stores templates like ``kpi.growth.<voice>_yoy``;
    plugging in the voice id yields the actual ``kpi_id`` to look up
    in ``historical_kpis``.
    """
    if template is None:
        return None
    return template.replace("<voice>", voice_id)


def _index_kpi_aggregates(
    db: Session, project_id: str
) -> dict[str, HistoricalKPI]:
    """Map ``kpi_id`` → ``HistoricalKPI`` AGG row for the project."""
    from sqlalchemy import select

    rows = db.execute(
        select(HistoricalKPI).where(
            HistoricalKPI.project_id == project_id,
            HistoricalKPI.year == "AGG",
        )
    ).scalars()
    return {r.kpi_id: r for r in rows}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def populate_defaults(
    db: Session,
    project_id: str,
    registries: Registries,
) -> PopulateReport:
    """Seed the ``assumptions`` table for every configured method.

    Returns a :class:`PopulateReport`. Caller owns the commit.
    """
    from sqlalchemy import select

    method_configs = list(
        db.execute(
            select(MethodConfig).where(
                MethodConfig.project_id == project_id
            )
        ).scalars()
    )

    valid_pairs = {(mc.voice_id, mc.method_id) for mc in method_configs}
    report = PopulateReport()
    report.pairs_deleted = delete_orphan_pairs(
        db, project_id, valid_pairs
    )

    # Snapshot existing user_input rows so we can report how many were
    # preserved. ``bulk_upsert_defaults`` will skip them internally;
    # we only need the count for the response.
    existing = list_assumptions(db, project_id)
    user_input_count = sum(1 for r in existing if r.source == "user_input")
    report.user_input_preserved = user_input_count

    kpi_aggs = _index_kpi_aggregates(db, project_id)

    entries: list[dict[str, Any]] = []
    for mc in method_configs:
        method = registries.methods.get(mc.method_id)
        if method is None:
            report.methods_skipped.append(
                f"{mc.voice_id}:{mc.method_id} (unknown method)"
            )
            continue
        names = _extract_assumption_names(method.get("formula_python"))
        if not names:
            # Methods like ``flat`` reference no assumption — nothing
            # to populate for the voice under that method.
            continue

        # Per-method KPI template: only one in the registry shape.
        # When a method has multiple assumption names, the template
        # is conventionally tied to the "primary" one (the first
        # extracted from the formula); the rest fall back to 0. This
        # is the documented limitation of the pilot registry shape.
        kpi_template = method.get("default_kpi_example")
        primary_name = names[0]

        # ``validation_range`` is not (yet) declared per assumption
        # in ``method_registry.yaml`` — leave NULL until a future
        # registry milestone adds it.
        validation_range = None

        for name in names:
            template = kpi_template if name == primary_name else None
            kpi_id = _resolve_default_kpi_id(template, mc.voice_id)
            agg = kpi_aggs.get(kpi_id) if kpi_id else None
            kpi_value: float | None = (
                agg.default_for_projection if agg is not None else None
            )

            if kpi_value is not None:
                source = "default_kpi"
                report.kpi_default_used += 3  # one per Y1/Y2/Y3 row
                report.populated += 3
                value = float(kpi_value)
            else:
                source = "fallback"
                report.fallback_used += 3
                report.populated += 3
                value = 0.0

            for year in YEARS:
                entries.append(
                    {
                        "voice_id": mc.voice_id,
                        "method_id": mc.method_id,
                        "assumption_name": name,
                        "year": year,
                        "value": value,
                        "source": source,
                        "default_kpi_id": kpi_id,
                        "validation_range": validation_range,
                    }
                )

    inserted, updated = bulk_upsert_defaults(db, project_id, entries)
    # ``populated`` already counts the entries we *intended* to write;
    # subtract the ones the repo skipped because they were user_input.
    skipped = max(0, len(entries) - inserted - updated)
    report.populated -= skipped
    # Splitting the lost rows between kpi_default/fallback is not
    # observable: bulk_upsert handles by primary key, not by source.
    # Cap each bucket to its share of the actual writes.
    if skipped:
        share_kpi = min(report.kpi_default_used, skipped)
        report.kpi_default_used -= share_kpi
        report.fallback_used -= max(0, skipped - share_kpi)

    return report


__all__ = ["PopulateReport", "populate_defaults"]
