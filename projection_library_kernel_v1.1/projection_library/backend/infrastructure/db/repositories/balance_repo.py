"""Repository functions for the M3 intake flow.

Each function takes a live :class:`~sqlalchemy.orm.Session` and either
mutates it (without committing) or runs a read query. The route layer
owns the commit boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.schemas.balance import ParsedBalance
from backend.infrastructure.db.models import Balance, RawVoice


def get_active_balance(db: Session, project_id: str) -> Balance | None:
    """Return the project's current (non-soft-deleted) balance, if any."""
    stmt = (
        select(Balance)
        .where(
            Balance.project_id == project_id,
            Balance.deleted_at.is_(None),
        )
        .order_by(Balance.uploaded_at.desc())
    )
    return db.execute(stmt).scalars().first()


def get_balance_by_id(
    db: Session, project_id: str, balance_id: str
) -> Balance | None:
    stmt = select(Balance).where(
        Balance.id == balance_id,
        Balance.project_id == project_id,
        Balance.deleted_at.is_(None),
    )
    return db.execute(stmt).scalars().first()


def soft_delete_balance(db: Session, balance: Balance) -> None:
    """Mark the balance as deleted; rows in ``raw_voices`` are kept.

    The active-balance query filters by ``deleted_at IS NULL`` so the
    soft-deleted record disappears from downstream flows immediately.
    Hard cascade happens only when the project itself is removed.
    """
    balance.deleted_at = datetime.now(timezone.utc)


def replace_active_balance(
    db: Session, project_id: str, parsed: ParsedBalance
) -> Balance:
    """Soft-delete the existing active balance (if any) and insert a new one."""
    existing = get_active_balance(db, project_id)
    if existing is not None:
        soft_delete_balance(db, existing)

    balance = Balance(
        project_id=project_id,
        source_type=parsed.source_type,
        raw_filename=parsed.raw_filename,
        years_present=list(parsed.years_present),
        voice_count=parsed.voice_count,
    )
    db.add(balance)
    db.flush()  # populate balance.id

    rows: list[RawVoice] = []
    for voice in parsed.voices:
        for year, amount in voice.values.items():
            if amount is None:
                continue
            rows.append(
                RawVoice(
                    balance_id=balance.id,
                    voice_user_label=voice.user_label,
                    voice_user_section=voice.user_section,
                    year=year,
                    amount=amount,
                    lfl_flag=True,
                )
            )
    if rows:
        db.add_all(rows)
    return balance


def list_raw_voices(db: Session, balance_id: str) -> list[RawVoice]:
    stmt = (
        select(RawVoice)
        .where(RawVoice.balance_id == balance_id)
        .order_by(RawVoice.id)
    )
    return list(db.execute(stmt).scalars().all())


def set_lfl_for_year(
    db: Session, balance_id: str, year: str, lfl: bool
) -> int:
    """Flip the ``lfl_flag`` for every raw voice of ``balance_id`` × ``year``.

    Returns the number of rows updated.
    """
    rows = list(
        db.execute(
            select(RawVoice).where(
                RawVoice.balance_id == balance_id,
                RawVoice.year == year,
            )
        ).scalars()
    )
    for row in rows:
        row.lfl_flag = lfl
    return len(rows)


def get_raw_voice(
    db: Session, balance_id: str, raw_voice_id: str
) -> RawVoice | None:
    """Fetch one ``raw_voices`` row scoped to a balance."""
    return db.execute(
        select(RawVoice).where(
            RawVoice.id == raw_voice_id,
            RawVoice.balance_id == balance_id,
        )
    ).scalars().first()


def upsert_raw_voice_value(
    db: Session,
    balance_id: str,
    voice_user_label: str,
    voice_user_section: str | None,
    year: str,
    amount: float,
) -> RawVoice:
    """Set ``amount`` on the ``(balance, label, section, year)`` row.

    Creates the row if it does not exist (Path 9.3 also supports
    backfilling a missing historical year on an existing voice). The
    uniqueness contract for raw voices is the (balance, label, section,
    year) tuple — mirroring the parser's writeback.
    """
    section_clause = (
        RawVoice.voice_user_section.is_(None)
        if voice_user_section is None
        else RawVoice.voice_user_section == voice_user_section
    )
    existing = db.execute(
        select(RawVoice).where(
            RawVoice.balance_id == balance_id,
            RawVoice.voice_user_label == voice_user_label,
            section_clause,
            RawVoice.year == year,
        )
    ).scalars().first()
    if existing is not None:
        existing.amount = amount
        return existing
    row = RawVoice(
        balance_id=balance_id,
        voice_user_label=voice_user_label,
        voice_user_section=voice_user_section,
        year=year,
        amount=amount,
        lfl_flag=True,
    )
    db.add(row)
    db.flush()
    return row


__all__ = [
    "get_active_balance",
    "get_balance_by_id",
    "get_raw_voice",
    "list_raw_voices",
    "replace_active_balance",
    "set_lfl_for_year",
    "soft_delete_balance",
    "upsert_raw_voice_value",
]
