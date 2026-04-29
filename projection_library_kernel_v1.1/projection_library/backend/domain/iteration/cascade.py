"""Iteration cascade — Path 9.2 (method change) and Path 9.3 (data modify).

Both helpers mutate the session without committing; the route layer
owns the transaction boundary, mirroring every other domain module in
the backend. Engine pre-conditions (E0) and validation block messages
are surfaced via :class:`IterationResult` flags rather than exceptions
so the route can decide the HTTP status.

Path 9.3 always re-runs the historical validator + KPI calculator +
quality scorer (those depend only on the mapped values and never raise
:class:`ProjectNotReady`). The engine run is gated on
``can_proceed=True``: if the new historical data introduced a ``block``,
the report is persisted but no snapshot is created — exactly what
``flows/09_iteration.md`` step 5 prescribes.

Path 9.2 only triggers a re-run when the project already has at least
one snapshot. Method changes on a fresh project (no first run yet) are
a no-op here: the user has to do the first ``POST /run`` explicitly,
which is the M6 contract we don't want to change implicitly.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.engine.executor import ProjectNotReady
from backend.domain.engine.snapshot_builder import (
    build_snapshot_values,
    build_validation_summary,
    serialise_validation_issues,
)
from backend.domain.intake import (
    resolve_mapped_values,
    run_historical_validation,
)
from backend.domain.kpi import compute_historical_kpis
from backend.domain.override.resolver import run_with_overrides
from backend.domain.quality import compute_quality_score
from backend.infrastructure.db.models import Project, Snapshot
from backend.infrastructure.db.repositories.m5_repos import (
    replace_historical_kpis,
    upsert_quality_score,
    upsert_validation_report,
)
from backend.infrastructure.db.repositories.snapshots_repo import create_snapshot
from backend.infrastructure.registry import Registries


@dataclass(frozen=True)
class IterationResult:
    """Outcome of a Path 9.2 / 9.3 cascade.

    ``snapshot`` is ``None`` when the engine was not run (validation
    block on Path 9.3, or no pre-existing snapshot on Path 9.2).
    ``validation_blocked`` is ``True`` only on Path 9.3 when the freshly
    computed historical report carries at least one ``block``-severity
    issue. ``engine_blocked`` is ``True`` when the engine was attempted
    but raised :class:`ProjectNotReady` (E0 not satisfied) — the
    cascade swallows it and the route maps it to a 409/422 if it cares.
    """

    snapshot: Snapshot | None
    validation_blocked: bool
    engine_blocked: bool
    validation_summary: dict
    engine_block_message: str | None = None


def _project_has_snapshot(db: Session, project_id: str) -> bool:
    return (
        db.execute(
            select(Snapshot.id).where(Snapshot.project_id == project_id).limit(1)
        ).scalars().first()
        is not None
    )


def _run_engine_and_snapshot(
    db: Session, project_id: str, registries: Registries
) -> tuple[Snapshot | None, str | None]:
    """Run the engine via ``run_with_overrides`` and persist a snapshot.

    Returns ``(snapshot, None)`` on success or ``(None, message)`` if
    :class:`ProjectNotReady` was raised. Other engine errors propagate.
    """
    try:
        result = run_with_overrides(project_id, db, registries)
    except ProjectNotReady as exc:
        return None, str(exc)

    state = result.final_state
    if state is None:
        return None, "engine did not expose final_state"

    snapshot = create_snapshot(
        db,
        project_id=project_id,
        run_timestamp=result.run_timestamp,
        status=result.status,
        duration_ms=result.duration_ms,
        validation_summary=build_validation_summary(state),
        validation_issues=serialise_validation_issues(state),
        approximation_log=list(result.approximation_log),
        pl_data=result.pl_data,
        sp_data=result.sp_data,
        cf_data=result.cf_data,
        projected_kpis=result.projected_kpis,
        error_message=None,
        values=build_snapshot_values(state),
    )
    db.flush()
    return snapshot, None


def iterate_historical_modify(
    project_id: str, db: Session, registries: Registries
) -> IterationResult:
    """Path 9.3 cascade: re-validate + re-kpi + re-quality + re-run engine.

    Skips the engine run when the validator emits a ``block`` issue,
    persisting the new validation report all the same so the UI can
    show the user what to fix.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise LookupError(f"project '{project_id}' not found")

    values = resolve_mapped_values(db, project_id)

    report = run_historical_validation(values, registries, project)
    upsert_validation_report(db, project_id, "historical", report)

    kpi_snapshot = compute_historical_kpis(values, registries)
    replace_historical_kpis(db, project_id, kpi_snapshot)

    quality = compute_quality_score(values, report, registries, project.tier_level)
    upsert_quality_score(db, project_id, quality)

    db.flush()

    summary = report.summary()

    if not report.can_proceed:
        return IterationResult(
            snapshot=None,
            validation_blocked=True,
            engine_blocked=False,
            validation_summary=summary,
        )

    snapshot, block_message = _run_engine_and_snapshot(db, project_id, registries)
    return IterationResult(
        snapshot=snapshot,
        validation_blocked=False,
        engine_blocked=block_message is not None,
        validation_summary=summary,
        engine_block_message=block_message,
    )


def iterate_method_change(
    project_id: str, db: Session, registries: Registries
) -> IterationResult:
    """Path 9.2 cascade: re-run engine iff a snapshot already exists.

    The first run after method changes is left to the user (explicit
    ``POST /run``); we only auto-trigger when the user is iterating on
    an already-projected model, which is the scenario the flow doc
    describes.
    """
    if not _project_has_snapshot(db, project_id):
        return IterationResult(
            snapshot=None,
            validation_blocked=False,
            engine_blocked=False,
            validation_summary={},
        )

    snapshot, block_message = _run_engine_and_snapshot(db, project_id, registries)
    return IterationResult(
        snapshot=snapshot,
        validation_blocked=False,
        engine_blocked=block_message is not None,
        validation_summary={},
        engine_block_message=block_message,
    )


__all__ = [
    "IterationResult",
    "iterate_historical_modify",
    "iterate_method_change",
]
