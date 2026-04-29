"""Repository for the ``overrides`` table (M11).

Same convention as ``method_configs_repo``: each function takes a
live :class:`~sqlalchemy.orm.Session`, mutates it without committing,
and lets the route own the transaction boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.infrastructure.db.models import Override


def create_override(
    db: Session,
    *,
    project_id: str,
    voice_id: str,
    year: str,
    delta_amount: float,
    nature: str,
    override_policy_class: str,
    user_note: str | None = None,
) -> Override:
    """Insert a new override row (always created active)."""
    row = Override(
        project_id=project_id,
        voice_id=voice_id,
        year=year,
        delta_amount=delta_amount,
        nature=nature,
        override_policy_class=override_policy_class,
        is_active=True,
        user_note=user_note,
    )
    db.add(row)
    db.flush()
    return row


def list_overrides(
    db: Session, project_id: str, *, active_only: bool = False
) -> list[Override]:
    stmt = (
        select(Override)
        .where(Override.project_id == project_id)
        .order_by(Override.created_at.desc(), Override.id.desc())
    )
    if active_only:
        stmt = stmt.where(Override.is_active.is_(True))
    return list(db.execute(stmt).scalars())


def get_override(
    db: Session, project_id: str, override_id: str
) -> Override | None:
    return db.execute(
        select(Override).where(
            Override.project_id == project_id,
            Override.id == override_id,
        )
    ).scalars().first()


def set_override_active(
    db: Session, override: Override, *, is_active: bool
) -> Override:
    """Toggle ``is_active`` and stamp ``deactivated_at`` on transitions.

    Reactivating an override clears ``deactivated_at`` so the audit
    trail reflects only the *current* deactivation, if any.
    """
    if override.is_active and not is_active:
        override.deactivated_at = datetime.now(timezone.utc)
    elif not override.is_active and is_active:
        override.deactivated_at = None
    override.is_active = is_active
    return override


def delete_override(db: Session, override: Override) -> None:
    db.delete(override)


__all__ = [
    "create_override",
    "delete_override",
    "get_override",
    "list_overrides",
    "set_override_active",
]
