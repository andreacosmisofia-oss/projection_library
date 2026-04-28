"""Repository for the ``drivers`` table (M7 driver intake).

Same convention as the other repos: each function takes a live
:class:`~sqlalchemy.orm.Session`, mutates it without committing, and
lets the route own the transaction boundary.

Skip is modelled as a marker row (``skipped=True``, ``year=""``); the
helper :func:`mark_driver_skipped` upserts that row in isolation, while
:func:`replace_driver_data` clears any skip marker as a side effect of
uploading data — uploading implies un-skipping.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.infrastructure.db.models import Driver


_SKIP_YEAR = ""


def list_drivers(db: Session, project_id: str) -> list[Driver]:
    return list(
        db.execute(
            select(Driver)
            .where(Driver.project_id == project_id)
            .order_by(Driver.driver_id, Driver.year)
        ).scalars()
    )


def list_drivers_for_id(
    db: Session, project_id: str, driver_id: str
) -> list[Driver]:
    return list(
        db.execute(
            select(Driver)
            .where(
                Driver.project_id == project_id,
                Driver.driver_id == driver_id,
            )
            .order_by(Driver.year)
        ).scalars()
    )


def is_skipped(db: Session, project_id: str, driver_id: str) -> bool:
    row = db.execute(
        select(Driver).where(
            Driver.project_id == project_id,
            Driver.driver_id == driver_id,
            Driver.skipped.is_(True),
        )
    ).scalars().first()
    return row is not None


def mark_driver_skipped(
    db: Session, project_id: str, driver_id: str
) -> Driver:
    """Upsert the (project, driver) skip marker.

    Wipes any data rows for the driver in the same transaction so the
    semantics are unambiguous: a skipped driver carries no values.
    """
    db.execute(
        delete(Driver).where(
            Driver.project_id == project_id,
            Driver.driver_id == driver_id,
        )
    )
    marker = Driver(
        project_id=project_id,
        driver_id=driver_id,
        type="skip",
        year=_SKIP_YEAR,
        value=None,
        unit=None,
        static_parameters=None,
        time_series=None,
        aging_buckets=None,
        skipped=True,
        uploaded_at=datetime.now(timezone.utc),
    )
    db.add(marker)
    return marker


def replace_driver_data(
    db: Session,
    project_id: str,
    driver_id: str,
    rows: Iterable[Driver],
) -> list[Driver]:
    """Drop every row for ``(project_id, driver_id)`` then add ``rows``.

    Used by the upload endpoint to make a re-upload deterministic
    (no leftover years from a previous submission). Also clears any
    skip marker — uploading data on a skipped driver un-skips it.
    """
    db.execute(
        delete(Driver).where(
            Driver.project_id == project_id,
            Driver.driver_id == driver_id,
        )
    )
    materialised = list(rows)
    for row in materialised:
        db.add(row)
    return materialised


__all__ = [
    "is_skipped",
    "list_drivers",
    "list_drivers_for_id",
    "mark_driver_skipped",
    "replace_driver_data",
]
