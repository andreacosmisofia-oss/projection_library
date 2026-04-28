"""Resolve raw_voices + mappings → MappedValues (M5).

The historical validator and the KPI calculator both consume a
``voice_id``-keyed view of the uploaded balance. M3 stores user labels
in ``raw_voices``; M4 will populate ``mappings`` with confirmed
``label → voice_id`` pairs (the M4 API surface is not built yet, but
the table is shipped here so M5 can read).

This module is the single seam between the persistence layer and
``validator_historical`` / ``kpi.calculator``: callers receive
:class:`MappedValues`, an immutable structure that hides the join.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.infrastructure.db.models import Balance, Mapping, RawVoice


@dataclass(frozen=True)
class MappedValues:
    """voice_id-indexed view of an uploaded balance.

    ``values[voice_id][year]`` returns the float amount, or raises
    KeyError if the (voice, year) pair was not provided.
    ``years_lfl`` is the ordered list of years marked LFL by the user
    (subset of ``years_present``); the historical validator uses it to
    decide whether cross-period rules apply.

    Multiple raw_voices rows can map to the same ``voice_id`` (the user
    splits "Materie prime" + "Manodopera" both into ``pl.cogs.total``
    via separate mappings); amounts are summed in that case.
    """

    project_id: str
    values: dict[str, dict[str, float]] = field(default_factory=dict)
    years_present: list[str] = field(default_factory=list)
    years_lfl: list[str] = field(default_factory=list)
    unmapped_labels: list[tuple[str, str | None]] = field(default_factory=list)
    label_to_voice: dict[tuple[str, str | None], str] = field(default_factory=dict)
    raw_by_section: dict[str, list[tuple[str, str, float]]] = field(
        default_factory=dict
    )

    def get(self, voice_id: str, year: str) -> float | None:
        """Return value or ``None`` if missing — never raises."""
        return self.values.get(voice_id, {}).get(year)

    def has(self, voice_id: str) -> bool:
        return voice_id in self.values

    def years_for(self, voice_id: str) -> list[str]:
        return list(self.values.get(voice_id, {}).keys())


_YEAR_ORDER = ("Y-3", "Y-2", "Y-1", "Y0")


def _sorted_years(years: Iterable[str]) -> list[str]:
    """Order years chronologically, falling back to lexicographic."""
    seen = list(dict.fromkeys(years))
    known = [y for y in _YEAR_ORDER if y in seen]
    extras = sorted(y for y in seen if y not in _YEAR_ORDER)
    return known + extras


def resolve_mapped_values(db: Session, project_id: str) -> MappedValues:
    """Build the voice_id-keyed view from the active balance + confirmed mappings.

    Raises
    ------
    LookupError
        If the project has no active balance.
    """
    balance = db.execute(
        select(Balance)
        .where(Balance.project_id == project_id, Balance.deleted_at.is_(None))
        .order_by(Balance.uploaded_at.desc())
    ).scalars().first()
    if balance is None:
        raise LookupError(
            f"project '{project_id}' has no active balance; upload one first"
        )

    rows = list(
        db.execute(
            select(RawVoice).where(RawVoice.balance_id == balance.id)
        ).scalars()
    )

    mapping_rows = list(
        db.execute(
            select(Mapping).where(
                Mapping.project_id == project_id,
                Mapping.confirmed_by_user.is_(True),
            )
        ).scalars()
    )
    label_to_voice: dict[tuple[str, str | None], str] = {
        (m.voice_user_label, m.voice_user_section): m.voice_id for m in mapping_rows
    }

    values: dict[str, dict[str, float]] = defaultdict(dict)
    years_present: set[str] = set()
    years_lfl: set[str] = set()
    unmapped: list[tuple[str, str | None]] = []
    seen_labels: set[tuple[str, str | None]] = set()
    raw_by_section: dict[str, list[tuple[str, str, float]]] = defaultdict(list)

    for row in rows:
        if row.amount is None:
            continue
        years_present.add(row.year)
        if row.lfl_flag:
            years_lfl.add(row.year)
        if row.voice_user_section:
            raw_by_section[row.voice_user_section].append(
                (row.voice_user_label, row.year, row.amount)
            )

        key = (row.voice_user_label, row.voice_user_section)
        voice_id = label_to_voice.get(key)
        if voice_id is None:
            if key not in seen_labels:
                unmapped.append(key)
                seen_labels.add(key)
            continue

        bucket = values[voice_id]
        bucket[row.year] = bucket.get(row.year, 0.0) + row.amount

    return MappedValues(
        project_id=project_id,
        values={k: dict(v) for k, v in values.items()},
        years_present=_sorted_years(years_present),
        years_lfl=_sorted_years(years_lfl),
        unmapped_labels=unmapped,
        label_to_voice=label_to_voice,
        raw_by_section={k: list(v) for k, v in raw_by_section.items()},
    )


__all__ = ["MappedValues", "resolve_mapped_values"]
