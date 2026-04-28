"""Auto-suggest mapper (Milestone M4).

Implements the strategy pipeline from ``flows/02_mapping.md``:

1. Per-company history (confidence 1.00, reason ``company_history``).
2. Synonym exact match (0.95, ``synonym_match``).
3. Canonical label exact match against the voice_id tail (0.90,
   ``label_exact``).
4. Fuzzy match via :mod:`backend.domain.intake.fuzzy` (ratio,
   ``fuzzy``).
5. Section adjustment (``±0.10`` boost, ``-0.20`` penalty) applied to
   the merged candidate set, clamped to ``[0, 1]``.
6. Sector-pack filter: voices the chosen pack disables are dropped.
   v1.1 sector packs encode disabled voices as freeform strings, so
   this is a no-op until the registry exposes a structured list.

The function is pure: it takes the raw voices, the synonym index, the
voice registry view and (optionally) a DB session for company-history
lookup. It returns the suggestion list and aggregate stats; no DB
writes happen here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.intake.fuzzy import top_matches
from backend.domain.intake.normalize import normalize_text
from backend.domain.intake.synonyms import SynonymIndex

CandidateReason = Literal[
    "company_history",
    "synonym_match",
    "label_exact",
    "fuzzy",
]

# Used as the secondary sort key so that tie-breaks at equal confidence
# preserve strategy precedence (e.g. confirmed company history beats a
# section-boosted synonym hit clamped to 1.0).
_REASON_RANK: dict[str, int] = {
    "company_history": 0,
    "synonym_match": 1,
    "label_exact": 2,
    "fuzzy": 3,
}

# Confidence ladder per flow doc.
CONFIDENCE_COMPANY_HISTORY = 1.00
CONFIDENCE_SYNONYM_MATCH = 0.95
CONFIDENCE_LABEL_EXACT = 0.90
SECTION_BOOST = 0.10
SECTION_PENALTY = 0.20

DEFAULT_TOP_K = 5
DEFAULT_THRESHOLD = 0.60

HIGH_CONFIDENCE = 0.85
MEDIUM_CONFIDENCE = 0.60


@dataclass(frozen=True)
class RawVoiceInput:
    """Minimal projection of a ``raw_voices`` row used by the mapper.

    The mapper doesn't care about year-by-year amounts during
    suggestion; the route layer aggregates rows into one per
    ``(label, section)`` and feeds the result here.
    """

    user_label: str
    user_section: str | None = None
    aggregate_amount: float | None = None


@dataclass(frozen=True)
class MappingCandidate:
    voice_id: str
    confidence: float
    reason: CandidateReason


@dataclass(frozen=True)
class MappingSuggestion:
    user_label: str
    user_section: str | None
    candidates: list[MappingCandidate]


@dataclass(frozen=True)
class MappingStats:
    total_voices: int
    high_confidence: int
    medium_confidence: int
    low_confidence: int
    no_match: int


# ---------------------------------------------------------------------------
# Section adjustment
# ---------------------------------------------------------------------------


_SECTION_TO_STATEMENTS: dict[str, frozenset[str]] = {
    "P&L": frozenset({"PL"}),
    "SP_assets": frozenset({"BS"}),
    "SP_liabilities": frozenset({"BS"}),
    "SP_equity": frozenset({"BS"}),
    "CF_operating": frozenset({"CF"}),
    "CF_investing": frozenset({"CF"}),
    "CF_financing": frozenset({"CF"}),
    "OTHER": frozenset(),
}


def _section_adjustment(
    user_section: str | None,
    voice: dict | None,
) -> float:
    """Return the section delta to apply to a candidate's confidence.

    +0.10 if the user section matches the voice statement, -0.20 if
    they conflict, 0.0 if either side is missing or ambiguous.
    """
    if not user_section or voice is None:
        return 0.0
    expected = _SECTION_TO_STATEMENTS.get(user_section)
    if not expected:
        return 0.0
    statement = voice.get("statement")
    if not statement:
        return 0.0
    if statement in expected:
        return SECTION_BOOST
    return -SECTION_PENALTY


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


# ---------------------------------------------------------------------------
# Strategy A — company history
# ---------------------------------------------------------------------------


def _company_history_lookup(
    db: Session | None,
    company_name: str | None,
    label: str,
) -> str | None:
    """Return a previously-confirmed voice_id for ``(company, label)``.

    The lookup is normalized on both sides so "Ricavi delle Vendite"
    today maps to the same row as "ricavi delle vendite" yesterday.
    Imported lazily because this module is also exercised in unit
    tests that don't carry the ORM around.
    """
    if db is None or not company_name:
        return None
    from backend.infrastructure.db.models import CompanyMapping

    company_norm = normalize_text(company_name)
    label_norm = normalize_text(label)
    if not company_norm or not label_norm:
        return None
    stmt = select(CompanyMapping).where(
        CompanyMapping.company_name_norm == company_norm,
        CompanyMapping.voice_user_label_norm == label_norm,
    )
    row = db.execute(stmt).scalars().first()
    if row is None:
        return None
    return row.voice_id_system


# ---------------------------------------------------------------------------
# Strategy C — voice_id tail label
# ---------------------------------------------------------------------------


def _voice_label_index(
    voices: dict[str, dict],
) -> dict[str, str]:
    """Build {normalized voice_id tail → voice_id}.

    The voice_registry has no ``label_canonical`` column today; the
    deepest segment of the dotted ``voice_id`` is the closest thing
    to a canonical label and is what humans tend to recognise.
    """
    out: dict[str, str] = {}
    for vid in voices:
        tail = vid.rsplit(".", 1)[-1]
        key = normalize_text(tail)
        if not key:
            continue
        # First voice wins on collision; collisions on the tail are
        # rare and an exact label-tail match is meant to be
        # unambiguous anyway.
        out.setdefault(key, vid)
    return out


# ---------------------------------------------------------------------------
# Sector-pack filter (currently a no-op)
# ---------------------------------------------------------------------------


def _allowed_voice_ids(
    voices: dict[str, dict],
    sector_packs: dict[str, dict] | None,
    sector_pack: str | None,
) -> set[str]:
    """Return the set of voice_ids active in the chosen sector pack.

    The current registry encodes ``voci_disabilitate`` as freeform
    descriptive strings (not voice_id lists). Until that's
    structured, every voice is allowed; the filter is a hook for the
    future, not dead code.
    """
    return set(voices.keys())


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def _merge_candidate(
    bag: dict[str, MappingCandidate],
    candidate: MappingCandidate,
) -> None:
    """Keep the higher-confidence entry per voice_id.

    Order matters for the ``reason`` label: a synonym hit at 0.95
    should not be downgraded to ``fuzzy`` just because the fuzzy
    pass scored the same voice at 0.93. We pick the entry with the
    larger confidence and, on ties, the earlier reason in the
    confidence ladder.
    """
    existing = bag.get(candidate.voice_id)
    if existing is None or candidate.confidence > existing.confidence:
        bag[candidate.voice_id] = candidate


def auto_suggest(
    raw_voices: Sequence[RawVoiceInput],
    *,
    sector_pack: str | None,
    company_name: str | None,
    synonyms: SynonymIndex,
    voices: dict[str, dict],
    sector_packs: dict[str, dict] | None = None,
    db: Session | None = None,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[list[MappingSuggestion], MappingStats]:
    """Run the strategy pipeline on every raw voice and aggregate stats.

    The function never raises on missing data: a raw voice with no
    candidates above the threshold simply gets an empty
    ``candidates`` list, and the stats counter ``no_match`` ticks up.
    """
    label_index = _voice_label_index(voices)
    allowed = _allowed_voice_ids(voices, sector_packs, sector_pack)

    # Restrict the synonym + fuzzy candidate sets to allowed voices so
    # disabled voices never reach the user (currently allowed == all).
    fuzzy_candidates: dict[str, list[str]] = {
        voice_id: list(synonyms.synonyms_for(voice_id))
        for voice_id in allowed
        if synonyms.synonyms_for(voice_id)
    }
    # Always include the normalized voice-id tail so the fuzzy pass
    # can reach voices that have no synonyms yet.
    for tail_norm, voice_id in label_index.items():
        if voice_id not in allowed:
            continue
        fuzzy_candidates.setdefault(voice_id, []).append(tail_norm)

    suggestions: list[MappingSuggestion] = []
    high = medium = low = empty = 0

    for raw in raw_voices:
        bag: dict[str, MappingCandidate] = {}

        # Strategy A — company history (highest priority, hard 1.0).
        history_vid = _company_history_lookup(db, company_name, raw.user_label)
        if history_vid is not None and history_vid in allowed:
            _merge_candidate(
                bag,
                MappingCandidate(
                    voice_id=history_vid,
                    confidence=CONFIDENCE_COMPANY_HISTORY,
                    reason="company_history",
                ),
            )

        # Strategy B — exact synonym match.
        synonym_vid = synonyms.lookup(raw.user_label)
        if synonym_vid is not None and synonym_vid in allowed:
            _merge_candidate(
                bag,
                MappingCandidate(
                    voice_id=synonym_vid,
                    confidence=CONFIDENCE_SYNONYM_MATCH,
                    reason="synonym_match",
                ),
            )

        # Strategy C — exact match on the voice_id tail.
        label_vid = label_index.get(normalize_text(raw.user_label))
        if label_vid is not None and label_vid in allowed:
            _merge_candidate(
                bag,
                MappingCandidate(
                    voice_id=label_vid,
                    confidence=CONFIDENCE_LABEL_EXACT,
                    reason="label_exact",
                ),
            )

        # Strategy D — fuzzy. Skip if A/B/C already hit ≥ synonym
        # confidence: fuzzy can't improve on that and only adds
        # noise to the candidate list.
        already_strong = any(
            c.confidence >= CONFIDENCE_SYNONYM_MATCH for c in bag.values()
        )
        if not already_strong:
            for voice_id, score in top_matches(
                raw.user_label,
                fuzzy_candidates,
                n=top_k * 2,  # widen pre-section-adjust pool
                threshold=threshold,
            ):
                if voice_id not in allowed:
                    continue
                _merge_candidate(
                    bag,
                    MappingCandidate(
                        voice_id=voice_id,
                        confidence=score,
                        reason="fuzzy",
                    ),
                )

        # Strategy E — section adjustment, applied last so every
        # candidate gets the same delta regardless of the strategy
        # that produced it. Company-history hits skip the adjustment
        # because the user has already confirmed them on a prior
        # project.
        adjusted: list[MappingCandidate] = []
        for cand in bag.values():
            if cand.reason == "company_history":
                adjusted.append(cand)
                continue
            delta = _section_adjustment(raw.user_section, voices.get(cand.voice_id))
            if delta == 0.0:
                adjusted.append(cand)
                continue
            new_conf = _clamp(cand.confidence + delta)
            adjusted.append(
                MappingCandidate(
                    voice_id=cand.voice_id,
                    confidence=new_conf,
                    reason=cand.reason,
                )
            )

        adjusted.sort(
            key=lambda c: (-c.confidence, _REASON_RANK.get(c.reason, 99), c.voice_id)
        )
        top = adjusted[:top_k]

        suggestions.append(
            MappingSuggestion(
                user_label=raw.user_label,
                user_section=raw.user_section,
                candidates=top,
            )
        )

        if not top:
            empty += 1
        else:
            best = top[0].confidence
            if best >= HIGH_CONFIDENCE:
                high += 1
            elif best >= MEDIUM_CONFIDENCE:
                medium += 1
            else:
                low += 1

    stats = MappingStats(
        total_voices=len(raw_voices),
        high_confidence=high,
        medium_confidence=medium,
        low_confidence=low,
        no_match=empty,
    )
    return suggestions, stats


# ---------------------------------------------------------------------------
# Sign-flip detection (helper used by the route)
# ---------------------------------------------------------------------------


_COST_PREFIXES: tuple[str, ...] = (
    "pl.cogs.",
    "pl.opex.",
    "pl.da.",
    "pl.impairment.",
    "pl.tax.",
    "pl.financial.interest_expense",
    "pl.financial.lease_interest",
)


def detect_sign_flip(
    raw_voices: Sequence[RawVoiceInput],
    suggestions: Sequence[MappingSuggestion],
) -> tuple[bool, bool]:
    """Return ``(detected, suggested)``.

    ``detected`` is True when at least one raw voice mapped to a cost
    voice carries a positive aggregate amount (IFRS-B convention
    expects costs negative). ``suggested`` is True when the **majority**
    of mapped cost voices are positive — the UI uses it as the
    default for the "auto-flip" toggle in the confirm step.
    """
    positives = 0
    negatives = 0
    for raw, suggestion in zip(raw_voices, suggestions):
        if raw.aggregate_amount is None:
            continue
        if not suggestion.candidates:
            continue
        top = suggestion.candidates[0].voice_id
        if not any(top.startswith(p) for p in _COST_PREFIXES):
            continue
        if raw.aggregate_amount > 0:
            positives += 1
        elif raw.aggregate_amount < 0:
            negatives += 1
    detected = positives > 0
    suggested = positives > negatives
    return detected, suggested


__all__ = [
    "MappingCandidate",
    "MappingStats",
    "MappingSuggestion",
    "RawVoiceInput",
    "auto_suggest",
    "detect_sign_flip",
]
