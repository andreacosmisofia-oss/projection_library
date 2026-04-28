"""Mapping routes — Milestone M4 (``flows/02_mapping.md``).

Three endpoints:

* ``POST /api/projects/{id}/mapping/suggest`` — runs the auto-suggest
  pipeline against the active balance and returns top-K candidates,
  stats, and sign-flip hints. No DB write.
* ``PUT /api/projects/{id}/mapping`` — persists the user's confirmed
  set, runs post-mapping validation, and updates the per-company
  memory used as strategy A on the next upload.
* ``GET /api/projects/{id}/mapping`` — returns the current mapping set.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.schemas.mapping import (
    MappingCandidate,
    MappingConfirmRequest,
    MappingConfirmResponse,
    MappingItem,
    MappingListResponse,
    MappingStats,
    MappingSuggestion,
    MappingSuggestResponse,
    MappingValidationIssue,
)
from backend.domain.intake.mapper import (
    RawVoiceInput,
    auto_suggest,
    detect_sign_flip,
)
from backend.infrastructure.db.database import get_db
from backend.infrastructure.db.models import Project
from backend.infrastructure.db.repositories.balance_repo import (
    get_active_balance,
    list_raw_voices,
)
from backend.infrastructure.db.repositories.mapping_repo import (
    list_mappings,
    replace_mappings,
    upsert_company_mapping,
)
from backend.infrastructure.registry import get_cache

router = APIRouter(prefix="/api/projects/{project_id}/mapping", tags=["mapping"])


_REVENUE_PREFIXES: tuple[str, ...] = ("pl.rev.",)
_REVENUE_TIER1: frozenset[str] = frozenset(
    {"pl.rev.gross_total", "pl.rev.net"}
)
_EQUITY_PREFIX = "bs.equity."
_ASSET_PREFIX = "bs.fa."
_LIABILITY_PREFIXES: tuple[str, ...] = ("bs.nfp.", "bs.provisions.", "bs.tax.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"project '{project_id}' not found",
        )
    return project


def _aggregate_raw_voices(rows) -> list[RawVoiceInput]:
    """Collapse the long-format ``raw_voices`` rows to one input per voice.

    The mapper only needs ``(label, section, aggregate_amount)``;
    summing across years gives a single signed scalar that's enough
    for sign-flip detection. Rows with null amounts are summed as 0.
    """
    bag: dict[tuple[str, str | None], list[float]] = defaultdict(list)
    for row in rows:
        key = (row.voice_user_label, row.voice_user_section)
        if row.amount is not None:
            bag[key].append(float(row.amount))
        else:
            bag.setdefault(key, [])  # ensure key exists even on null years
    return [
        RawVoiceInput(
            user_label=label,
            user_section=section,
            aggregate_amount=sum(values) if values else None,
        )
        for (label, section), values in bag.items()
    ]


def _post_mapping_issues(
    items: list[dict],
) -> list[MappingValidationIssue]:
    """Flow §3 post-mapping checks.

    Two production rules carried over from the flow doc:

    * **Tier-1 revenue must be derivable**: at least one mapping
      under ``pl.rev.*`` (or one of the totals) must exist and not
      be skipped, otherwise the project can't compute a revenue
      figure.
    * **Equity must be present when both assets and liabilities are
      mapped**: SP cannot balance without it.

    Skipped rows are excluded from the predicate sets — a "skip"
    declares that the line will not be considered.
    """
    issues: list[MappingValidationIssue] = []

    confirmed_voice_ids: set[str] = set()
    for item in items:
        if item.get("skipped"):
            continue
        vid = item.get("voice_id_system")
        if vid:
            confirmed_voice_ids.add(vid)

    has_revenue = any(
        vid in _REVENUE_TIER1 or vid.startswith(_REVENUE_PREFIXES[0])
        for vid in confirmed_voice_ids
    )
    if not has_revenue:
        issues.append(
            MappingValidationIssue(
                code="MAP_001",
                severity="block",
                message=(
                    "no revenue mapped: at least one voice under 'pl.rev.*' "
                    "(or pl.rev.gross_total / pl.rev.net) is required for "
                    "tier-1 validation"
                ),
            )
        )

    has_assets = any(vid.startswith(_ASSET_PREFIX) for vid in confirmed_voice_ids)
    has_liab = any(
        any(vid.startswith(p) for p in _LIABILITY_PREFIXES)
        for vid in confirmed_voice_ids
    )
    has_equity = any(vid.startswith(_EQUITY_PREFIX) for vid in confirmed_voice_ids)
    if has_assets and has_liab and not has_equity:
        issues.append(
            MappingValidationIssue(
                code="MAP_002",
                severity="block",
                message=(
                    "balance sheet cannot reconcile: assets and liabilities "
                    "are mapped but no equity voice was confirmed"
                ),
            )
        )

    return issues


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/suggest", response_model=MappingSuggestResponse)
def suggest_mapping(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> MappingSuggestResponse:
    project = _get_project_or_404(db, project_id)
    balance = get_active_balance(db, project_id)
    if balance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no active balance for project '{project_id}'",
        )
    rows = list_raw_voices(db, balance.id)
    raw_inputs = _aggregate_raw_voices(rows)

    registries = get_cache().get()
    suggestions, stats = auto_suggest(
        raw_inputs,
        sector_pack=project.sector_pack,
        company_name=project.company_name or project.name,
        synonyms=registries.synonyms,
        voices=registries.voices,
        sector_packs=registries.sector_packs,
        db=db,
    )
    detected, suggested = detect_sign_flip(raw_inputs, suggestions)

    return MappingSuggestResponse(
        suggestions=[
            MappingSuggestion(
                user_label=s.user_label,
                user_section=s.user_section,
                candidates=[
                    MappingCandidate(
                        voice_id=c.voice_id,
                        confidence=c.confidence,
                        reason=c.reason,
                    )
                    for c in s.candidates
                ],
            )
            for s in suggestions
        ],
        stats=MappingStats(
            total_voices=stats.total_voices,
            high_confidence=stats.high_confidence,
            medium_confidence=stats.medium_confidence,
            low_confidence=stats.low_confidence,
            no_match=stats.no_match,
        ),
        sign_flip_detected=detected,
        suggested_flip=suggested,
    )


@router.put("", response_model=MappingConfirmResponse)
def confirm_mapping(
    project_id: str,
    payload: MappingConfirmRequest,
    db: Annotated[Session, Depends(get_db)],
) -> MappingConfirmResponse:
    project = _get_project_or_404(db, project_id)

    items: list[dict] = []
    for entry in payload.mappings:
        if not entry.skipped and not entry.voice_id_system:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"mapping for label '{entry.user_label}' must either "
                    f"point to a voice_id_system or set skipped=true"
                ),
            )
        items.append(
            {
                "voice_user_label": entry.user_label,
                "voice_user_section": entry.user_section,
                "voice_id_system": entry.voice_id_system if not entry.skipped else None,
                "confidence": entry.confidence,
                "auto_suggested": entry.auto_suggested,
                "skipped": entry.skipped,
                "sign_flip_applied": payload.sign_flip_applied,
            }
        )

    issues = _post_mapping_issues(items)
    has_block = any(i.severity == "block" for i in issues)

    saved_rows = replace_mappings(db, project_id, items)

    # Mirror confirmed mappings into the per-company memory so the next
    # project for the same company can use strategy A. Skipped rows
    # are excluded.
    company_name = (project.company_name or project.name).strip()
    if company_name and not has_block:
        for entry in payload.mappings:
            if entry.skipped or not entry.voice_id_system:
                continue
            upsert_company_mapping(
                db,
                company_name=company_name,
                voice_user_label=entry.user_label,
                voice_id_system=entry.voice_id_system,
            )

    db.commit()

    return MappingConfirmResponse(
        saved=len(saved_rows),
        validation_issues=issues,
        ready_for_validation=not has_block,
    )


@router.get("", response_model=MappingListResponse)
def get_mapping(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> MappingListResponse:
    _get_project_or_404(db, project_id)
    rows = list_mappings(db, project_id)
    return MappingListResponse(
        count=len(rows),
        items=[MappingItem.model_validate(r) for r in rows],
    )


__all__ = ["router"]
