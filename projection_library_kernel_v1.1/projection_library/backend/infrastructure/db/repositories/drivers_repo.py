"""Repository for the ``drivers`` table (M7).

Same convention as the other repositories in this package: each
function takes a live :class:`~sqlalchemy.orm.Session` and either
mutates it (without committing) or runs a read query. The route owns
the commit.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.infrastructure.db.models import Driver


DRIVER_STATUS_ACTIVE = "active"
DRIVER_STATUS_SKIPPED = "skipped"


def list_drivers(db: Session, project_id: str) -> list[Driver]:
    return list(
        db.execute(
            select(Driver)
            .where(Driver.project_id == project_id)
            .order_by(Driver.driver_id)
        ).scalars()
    )


def get_driver(db: Session, project_id: str, driver_id: str) -> Driver | None:
    return db.execute(
        select(Driver).where(
            Driver.project_id == project_id,
            Driver.driver_id == driver_id,
        )
    ).scalars().first()


def upsert_driver(
    db: Session,
    project_id: str,
    driver_id: str,
    driver_type: str,
    values: dict | None,
    static_parameters: dict | None,
    unit: str | None,
) -> Driver:
    """Insert or update one ``drivers`` row.

    Touching a driver always flips its status back to ``active`` —
    skipping then uploading is a valid path and the user expects the
    upload to win. ``uploaded_at`` is left untouched on update so the
    UI can show "first upload" vs. "last edit"; ``updated_at`` is bumped
    by SQLAlchemy on every flush.
    """
    existing = get_driver(db, project_id, driver_id)
    now = datetime.now(timezone.utc)
    if existing is None:
        row = Driver(
            project_id=project_id,
            driver_id=driver_id,
            status=DRIVER_STATUS_ACTIVE,
            driver_type=driver_type,
            values=values,
            static_parameters=static_parameters,
            unit=unit,
            uploaded_at=now,
            updated_at=now,
        )
        db.add(row)
        return row
    existing.status = DRIVER_STATUS_ACTIVE
    existing.driver_type = driver_type
    existing.values = values
    existing.static_parameters = static_parameters
    existing.unit = unit
    existing.updated_at = now
    return existing


def mark_driver_skipped(
    db: Session,
    project_id: str,
    driver_id: str,
    driver_type: str,
) -> Driver:
    """Idempotent: creates a row with status=skipped if absent.

    A user can skip a driver before ever uploading data. We materialise
    the row so the GET endpoint can reflect the choice deterministically
    instead of inferring it from absence.
    """
    existing = get_driver(db, project_id, driver_id)
    now = datetime.now(timezone.utc)
    if existing is None:
        row = Driver(
            project_id=project_id,
            driver_id=driver_id,
            status=DRIVER_STATUS_SKIPPED,
            driver_type=driver_type,
            values=None,
            static_parameters=None,
            unit=None,
            uploaded_at=now,
            updated_at=now,
        )
        db.add(row)
        return row
    existing.status = DRIVER_STATUS_SKIPPED
    existing.updated_at = now
    return existing


__all__ = [
    "DRIVER_STATUS_ACTIVE",
    "DRIVER_STATUS_SKIPPED",
    "get_driver",
    "list_drivers",
    "mark_driver_skipped",
    "upsert_driver",
]
