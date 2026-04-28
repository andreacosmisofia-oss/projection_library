"""Repository for the ``method_configs`` table (M6 Expert mode).

Same convention as ``m5_repos`` and ``balance_repo``: each function
takes a live :class:`~sqlalchemy.orm.Session` and either mutates it
(without committing) or runs a read query. The route owns the commit.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.infrastructure.db.models import MethodConfig


def list_method_configs(db: Session, project_id: str) -> list[MethodConfig]:
    return list(
        db.execute(
            select(MethodConfig)
            .where(MethodConfig.project_id == project_id)
            .order_by(MethodConfig.voice_id)
        ).scalars()
    )


def get_method_config(
    db: Session, project_id: str, voice_id: str
) -> MethodConfig | None:
    return db.execute(
        select(MethodConfig).where(
            MethodConfig.project_id == project_id,
            MethodConfig.voice_id == voice_id,
        )
    ).scalars().first()


def upsert_method_config(
    db: Session,
    project_id: str,
    voice_id: str,
    method_id: str,
    method_technical_code: str | None,
    is_default: bool,
    source: str,
) -> MethodConfig:
    """Insert or update one ``method_configs`` row.

    The unique index on ``(project_id, voice_id)`` keeps the lookup
    deterministic. ``configured_at`` is bumped on every write so the
    UI can show last-edited timestamps.
    """
    existing = get_method_config(db, project_id, voice_id)
    now = datetime.now(timezone.utc)
    if existing is None:
        row = MethodConfig(
            project_id=project_id,
            voice_id=voice_id,
            method_id=method_id,
            method_technical_code=method_technical_code,
            is_default=is_default,
            source=source,
            configured_at=now,
        )
        db.add(row)
        return row
    existing.method_id = method_id
    existing.method_technical_code = method_technical_code
    existing.is_default = is_default
    existing.source = source
    existing.configured_at = now
    return existing


__all__ = [
    "get_method_config",
    "list_method_configs",
    "upsert_method_config",
]
