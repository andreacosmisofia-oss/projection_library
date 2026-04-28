"""Repository for the M8 ``assumptions`` and ``assumption_curve_configs``.

Same convention as the rest of the layer (``m5_repos``, ``balance_repo``,
``drivers_repo``): each function takes a live
:class:`~sqlalchemy.orm.Session`, mutates it without committing, and
lets the route own the transaction boundary.

The repo owns just enough policy to keep the unique-key invariants:

* ``replace_defaults_for_project`` drops every row whose ``source`` is
  ``default_kpi`` or ``fallback`` and re-inserts the freshly computed
  defaults — ``user_input`` rows survive verbatim, mirroring the
  idempotency contract from ``flows/06_assumption_compilation.md`` §API.
* ``upsert_assumption_value`` flips ``source`` to ``user_input`` and
  stamps ``user_modified_at`` so the populator can tell at a glance
  what to leave alone on the next run.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from backend.domain.assumptions.populator import (
    SOURCE_DEFAULT_KPI,
    SOURCE_FALLBACK,
    SOURCE_USER_INPUT,
    AssumptionDefault,
    PROJECTION_YEARS,
)
from backend.infrastructure.db.models import (
    Assumption,
    AssumptionCurveConfig,
)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def list_assumptions(db: Session, project_id: str) -> list[Assumption]:
    return list(
        db.execute(
            select(Assumption)
            .where(Assumption.project_id == project_id)
            .order_by(
                Assumption.voice_id,
                Assumption.method_id,
                Assumption.assumption_name,
                Assumption.year,
            )
        ).scalars()
    )


def list_curves(db: Session, project_id: str) -> list[AssumptionCurveConfig]:
    return list(
        db.execute(
            select(AssumptionCurveConfig)
            .where(AssumptionCurveConfig.project_id == project_id)
            .order_by(
                AssumptionCurveConfig.voice_id,
                AssumptionCurveConfig.method_id,
                AssumptionCurveConfig.assumption_name,
            )
        ).scalars()
    )


def get_curve(
    db: Session,
    project_id: str,
    voice_id: str,
    method_id: str,
    assumption_name: str,
) -> AssumptionCurveConfig | None:
    return db.execute(
        select(AssumptionCurveConfig).where(
            AssumptionCurveConfig.project_id == project_id,
            AssumptionCurveConfig.voice_id == voice_id,
            AssumptionCurveConfig.method_id == method_id,
            AssumptionCurveConfig.assumption_name == assumption_name,
        )
    ).scalars().first()


def find_assumptions_for_voice_name(
    db: Session,
    project_id: str,
    voice_id: str,
    assumption_name: str,
) -> list[Assumption]:
    """Return every per-year row matching the (project, voice, name).

    The PATCH endpoint uses this to discover the active ``method_id``
    without forcing it into the URL: ``method_configs`` already pins
    one method per voice, so the result is normally three rows (Y1/Y2/Y3
    for one method).
    """
    return list(
        db.execute(
            select(Assumption)
            .where(
                Assumption.project_id == project_id,
                Assumption.voice_id == voice_id,
                Assumption.assumption_name == assumption_name,
            )
            .order_by(Assumption.method_id, Assumption.year)
        ).scalars()
    )


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def _assumption_rows_from_default(
    project_id: str,
    default: AssumptionDefault,
    now: datetime,
) -> list[Assumption]:
    """Expand one :class:`AssumptionDefault` into three per-year rows.

    The flat-curve baseline: same value Y1/Y2/Y3. Drift toward a target
    is left to the user (``POST .../curve``) and overwrites these rows.
    """
    rows: list[Assumption] = []
    range_min, range_max = default.validation_range
    for year in PROJECTION_YEARS:
        rows.append(
            Assumption(
                project_id=project_id,
                voice_id=default.voice_id,
                method_id=default.method_id,
                assumption_name=default.assumption_name,
                year=year,
                value=default.value,
                source=default.source,
                default_kpi_id=default.default_kpi_id,
                calibration_score=default.calibration_score,
                validation_range_min=range_min,
                validation_range_max=range_max,
                parameterized=default.parameterized,
                user_modified_at=None,
                created_at=now,
            )
        )
    return rows


def replace_defaults_for_project(
    db: Session,
    project_id: str,
    defaults: Iterable[AssumptionDefault],
) -> dict[str, int]:
    """Re-seed ``default_kpi`` / ``fallback`` rows from ``defaults``.

    ``user_input`` rows are preserved iff they belong to a (voice,
    method, assumption_name) tuple still present in the new defaults.
    Stale user inputs (whose method has been swapped, or whose
    assumption name is no longer referenced by the method's formula)
    are dropped — leaving them around would create orphan cells with
    no UI representation.

    Returns the breakdown ``{populated, kpi_default_used, fallback_used,
    preserved_user_input}`` consumed by the populate endpoint response.
    """
    new_keys: set[tuple[str, str, str]] = set()
    counts = {
        "populated": 0,
        "kpi_default_used": 0,
        "fallback_used": 0,
        "preserved_user_input": 0,
    }
    materialised = list(defaults)
    for d in materialised:
        new_keys.add((d.voice_id, d.method_id, d.assumption_name))

    # Step 1: snapshot which user_input rows we want to preserve.
    existing_user_inputs = list(
        db.execute(
            select(Assumption).where(
                Assumption.project_id == project_id,
                Assumption.source == SOURCE_USER_INPUT,
            )
        ).scalars()
    )
    preserved_keys: set[tuple[str, str, str, str]] = set()
    for row in existing_user_inputs:
        key3 = (row.voice_id, row.method_id, row.assumption_name)
        if key3 in new_keys:
            preserved_keys.add(
                (row.voice_id, row.method_id, row.assumption_name, row.year)
            )

    # Step 2: drop everything except the user-input rows we keep.
    if preserved_keys:
        # SQL alchemy doesn't make tuple-IN especially elegant on mixed
        # backends, so build a per-row OR — the cardinalities are small
        # (a few hundred rows max for a pilot project).
        keep_clauses = [
            and_(
                Assumption.voice_id == v,
                Assumption.method_id == m,
                Assumption.assumption_name == n,
                Assumption.year == y,
            )
            for (v, m, n, y) in preserved_keys
        ]
        db.execute(
            delete(Assumption).where(
                Assumption.project_id == project_id,
                ~or_(*keep_clauses),
            )
        )
    else:
        db.execute(
            delete(Assumption).where(Assumption.project_id == project_id)
        )

    # Step 3: insert the new defaults, skipping (year-)cells already
    # covered by a preserved user_input row.
    now = datetime.now(timezone.utc)
    for default in materialised:
        rows = _assumption_rows_from_default(project_id, default, now)
        for row in rows:
            if (
                row.voice_id,
                row.method_id,
                row.assumption_name,
                row.year,
            ) in preserved_keys:
                counts["preserved_user_input"] += 1
                continue
            db.add(row)
            counts["populated"] += 1
            if default.source == SOURCE_DEFAULT_KPI:
                counts["kpi_default_used"] += 1
            elif default.source == SOURCE_FALLBACK:
                counts["fallback_used"] += 1

    # Step 4: drop any orphan curve configs whose (voice, method, name)
    # is no longer in the new defaults — same idea as user_input.
    if new_keys:
        keep_clauses = [
            and_(
                AssumptionCurveConfig.voice_id == v,
                AssumptionCurveConfig.method_id == m,
                AssumptionCurveConfig.assumption_name == n,
            )
            for (v, m, n) in new_keys
        ]
        db.execute(
            delete(AssumptionCurveConfig).where(
                AssumptionCurveConfig.project_id == project_id,
                ~or_(*keep_clauses),
            )
        )
    else:
        db.execute(
            delete(AssumptionCurveConfig).where(
                AssumptionCurveConfig.project_id == project_id,
            )
        )

    return counts


def upsert_assumption_value(
    db: Session,
    project_id: str,
    voice_id: str,
    method_id: str,
    assumption_name: str,
    year: str,
    value: float,
) -> Assumption:
    """Update one cell, force ``source=user_input``, stamp the timestamp.

    Raises ``LookupError`` when the row doesn't exist — the route layer
    converts that to a 404. We don't auto-create rows here: the
    populate endpoint is the single seam that materialises the default
    schema, and PATCHing a non-existent cell almost always means the
    client is targeting a stale (voice, method) pair.
    """
    row = db.execute(
        select(Assumption).where(
            Assumption.project_id == project_id,
            Assumption.voice_id == voice_id,
            Assumption.method_id == method_id,
            Assumption.assumption_name == assumption_name,
            Assumption.year == year,
        )
    ).scalars().first()
    if row is None:
        raise LookupError(
            f"assumption ({project_id}, {voice_id}, {method_id}, "
            f"{assumption_name}, {year}) not found"
        )
    row.value = value
    row.source = SOURCE_USER_INPUT
    row.user_modified_at = datetime.now(timezone.utc)
    return row


def upsert_assumption_value_for_year(
    db: Session,
    project_id: str,
    voice_id: str,
    method_id: str,
    assumption_name: str,
    year: str,
    value: float,
    *,
    source: str = SOURCE_USER_INPUT,
    mark_modified: bool = True,
) -> Assumption:
    """Internal helper used by the curve endpoint.

    Same shape as :func:`upsert_assumption_value` but lets the curve
    endpoint reuse the lookup-and-update for all three years without
    paying the LookupError ergonomics. ``mark_modified=False`` would be
    set if a future flow wanted to apply a curve as a default refresh
    rather than a user override; the curve endpoint always writes as
    ``user_input`` because it's an explicit user action.
    """
    row = db.execute(
        select(Assumption).where(
            Assumption.project_id == project_id,
            Assumption.voice_id == voice_id,
            Assumption.method_id == method_id,
            Assumption.assumption_name == assumption_name,
            Assumption.year == year,
        )
    ).scalars().first()
    if row is None:
        raise LookupError(
            f"assumption ({project_id}, {voice_id}, {method_id}, "
            f"{assumption_name}, {year}) not found"
        )
    row.value = value
    row.source = source
    if mark_modified:
        row.user_modified_at = datetime.now(timezone.utc)
    return row


def upsert_curve(
    db: Session,
    project_id: str,
    voice_id: str,
    method_id: str,
    assumption_name: str,
    curve_type: str,
) -> AssumptionCurveConfig:
    """Insert or update the curve-shape row (one per (voice, method, name))."""
    existing = get_curve(
        db, project_id, voice_id, method_id, assumption_name
    )
    now = datetime.now(timezone.utc)
    if existing is None:
        row = AssumptionCurveConfig(
            project_id=project_id,
            voice_id=voice_id,
            method_id=method_id,
            assumption_name=assumption_name,
            curve_type=curve_type,
            configured_at=now,
        )
        db.add(row)
        return row
    existing.curve_type = curve_type
    existing.configured_at = now
    return existing


__all__ = [
    "find_assumptions_for_voice_name",
    "get_curve",
    "list_assumptions",
    "list_curves",
    "replace_defaults_for_project",
    "upsert_assumption_value",
    "upsert_assumption_value_for_year",
    "upsert_curve",
]
