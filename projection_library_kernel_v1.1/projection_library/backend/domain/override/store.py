"""Domain-facing read view over the overrides table (M11).

Thin layer the engine uses when it needs the *active* override list as
plain :class:`~backend.domain.engine.value_resolver.Override`
dataclasses (no ORM coupling for the engine module). Mutating
operations stay in the route layer via
:mod:`backend.infrastructure.db.repositories.overrides_repo`; this
module is read-only by design.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.engine.value_resolver import Override
from backend.infrastructure.db.models import Override as OverrideRow


def list_active_overrides_for_state(
    db: Session, project_id: str
) -> list[Override]:
    """Return active overrides as engine ``Override`` dataclasses."""
    rows: Iterable[OverrideRow] = db.execute(
        select(OverrideRow)
        .where(OverrideRow.project_id == project_id)
        .where(OverrideRow.is_active.is_(True))
    ).scalars()
    return [
        Override(
            voice_id=row.voice_id,
            year=row.year,
            delta_amount=float(row.delta_amount),
            is_active=True,
            nature=row.nature,
        )
        for row in rows
    ]


__all__ = ["list_active_overrides_for_state"]
