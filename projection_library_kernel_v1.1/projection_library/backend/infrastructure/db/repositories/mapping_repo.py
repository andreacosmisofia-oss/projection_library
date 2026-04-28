"""Repository functions for the M4 mapping flow.

Same boundary contract as ``balance_repo``: each function accepts a
live :class:`~sqlalchemy.orm.Session`, mutates it without committing,
and the route owns the commit. Persistence is the only thing here —
the suggest pipeline lives in :mod:`backend.domain.intake.mapper`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.intake.normalize import normalize_text
from backend.infrastructure.db.models import CompanyMapping, Mapping


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def list_mappings(db: Session, project_id: str) -> list[Mapping]:
    stmt = (
        select(Mapping)
        .where(Mapping.project_id == project_id)
        .order_by(Mapping.created_at, Mapping.id)
    )
    return list(db.execute(stmt).scalars().all())


def replace_mappings(
    db: Session,
    project_id: str,
    items: list[dict],
) -> list[Mapping]:
    """Replace the entire mapping set for ``project_id`` in one transaction.

    Each ``items`` entry is a dict with keys ``voice_user_label``,
    ``voice_user_section``, ``voice_id_system`` (or ``None``),
    ``skipped``, ``confidence`` (optional), ``auto_suggested``
    (optional), ``sign_flip_applied`` (optional).

    The semantics are "user confirmed the whole list": we wipe the
    existing rows and insert the new ones. This avoids the merge
    complexity of a partial upsert and matches the wizard UX where
    the user submits the table as a unit.
    """
    db.execute(
        Mapping.__table__.delete().where(Mapping.project_id == project_id)
    )
    rows: list[Mapping] = []
    for item in items:
        rows.append(
            Mapping(
                project_id=project_id,
                voice_user_label=item["voice_user_label"],
                voice_user_section=item.get("voice_user_section"),
                voice_id_system=item.get("voice_id_system"),
                confidence=item.get("confidence"),
                auto_suggested=bool(item.get("auto_suggested", False)),
                confirmed_by_user=True,
                skipped=bool(item.get("skipped", False)),
                sign_flip_applied=bool(item.get("sign_flip_applied", False)),
            )
        )
    if rows:
        db.add_all(rows)
        db.flush()
    return rows


def upsert_company_mapping(
    db: Session,
    *,
    company_name: str,
    voice_user_label: str,
    voice_id_system: str,
) -> CompanyMapping:
    """Insert or refresh a per-company memory row.

    Both keys are normalised before the lookup so casing/accents
    don't fragment the table. ``last_used_at`` is bumped on every
    confirmation so the most recently used mapping wins on conflicts
    (current schema enforces uniqueness on the pair, so "wins" is
    moot today, but the field is also useful for a future "recently
    used" UI).
    """
    company_norm = normalize_text(company_name)
    label_norm = normalize_text(voice_user_label)
    if not company_norm or not label_norm or not voice_id_system:
        raise ValueError("company_mapping requires non-empty company, label, voice")

    existing = db.execute(
        select(CompanyMapping).where(
            CompanyMapping.company_name_norm == company_norm,
            CompanyMapping.voice_user_label_norm == label_norm,
        )
    ).scalars().first()
    if existing is not None:
        existing.voice_id_system = voice_id_system
        existing.last_used_at = _utcnow()
        return existing
    row = CompanyMapping(
        company_name_norm=company_norm,
        voice_user_label_norm=label_norm,
        voice_id_system=voice_id_system,
    )
    db.add(row)
    db.flush()
    return row


__all__ = [
    "list_mappings",
    "replace_mappings",
    "upsert_company_mapping",
]
