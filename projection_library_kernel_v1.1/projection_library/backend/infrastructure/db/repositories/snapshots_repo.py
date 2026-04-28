"""Repository for ``snapshots`` and ``snapshot_values`` (M10).

Same convention as the other repos: each function takes a live
:class:`~sqlalchemy.orm.Session`, mutates it without committing, and
lets the route own the transaction boundary.

Snapshots are append-only: each ``POST /run`` creates a new row and
the history is preserved. ``GET /snapshot/latest`` selects by
``created_at DESC``; the dashboard never queries by id, so no
secondary index is needed beyond the one on
``(project_id, created_at)``.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.domain.engine.snapshot_builder import SnapshotValueRow
from backend.infrastructure.db.models import Snapshot, SnapshotValue


def create_snapshot(
    db: Session,
    *,
    project_id: str,
    run_timestamp,
    status: str,
    duration_ms: int,
    validation_summary: dict,
    validation_issues: list,
    approximation_log: list,
    pl_data: dict,
    sp_data: dict,
    cf_data: dict,
    projected_kpis: dict,
    error_message: str | None,
    values: Iterable[SnapshotValueRow],
) -> Snapshot:
    """Create a snapshot header and its normalised value rows."""
    snapshot = Snapshot(
        project_id=project_id,
        run_timestamp=run_timestamp,
        status=status,
        duration_ms=duration_ms,
        error_message=error_message,
        validation_summary=dict(validation_summary),
        validation_issues=list(validation_issues),
        approximation_log=list(approximation_log),
        pl_data=dict(pl_data),
        sp_data=dict(sp_data),
        cf_data=dict(cf_data),
        projected_kpis=dict(projected_kpis),
    )
    db.add(snapshot)
    db.flush()  # populate snapshot.id for the FK on values

    for row in values:
        db.add(
            SnapshotValue(
                snapshot_id=snapshot.id,
                voice_id=row.voice_id,
                year=row.year,
                value=row.value,
                base_value=row.base_value,
                override_delta=row.override_delta,
            )
        )
    return snapshot


def get_latest_snapshot(db: Session, project_id: str) -> Snapshot | None:
    """Return the most recent snapshot for the project, or ``None``.

    Eager-loads ``values`` so the route can serialise without a second
    round-trip.
    """
    return db.execute(
        select(Snapshot)
        .where(Snapshot.project_id == project_id)
        .order_by(Snapshot.created_at.desc(), Snapshot.id.desc())
        .options(selectinload(Snapshot.values))
        .limit(1)
    ).scalars().first()


def list_snapshots(
    db: Session, project_id: str, limit: int = 5
) -> list[Snapshot]:
    """Return the latest ``limit`` snapshot headers (no values eager-loaded)."""
    return list(
        db.execute(
            select(Snapshot)
            .where(Snapshot.project_id == project_id)
            .order_by(Snapshot.created_at.desc(), Snapshot.id.desc())
            .limit(limit)
        ).scalars()
    )


__all__ = [
    "create_snapshot",
    "get_latest_snapshot",
    "list_snapshots",
]
