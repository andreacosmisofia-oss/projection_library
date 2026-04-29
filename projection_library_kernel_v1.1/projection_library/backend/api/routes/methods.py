"""Method-selection routes — Milestone M6, Expert subset.

Implements ``GET /api/projects/{project_id}/methods`` and
``PUT /api/projects/{project_id}/methods/{voice_id}``. ``init`` and
``apply-pack`` are deliberately out of scope here: GET merges DB
rows with ``voice.default_method`` from the registry on the fly, so
the table starts working without any pre-population step.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.api.schemas.methods import (
    MethodConfigEntry,
    MethodConfigList,
    MethodConfigSummary,
    MethodUpdate,
)
from backend.domain.engine.executor import ProjectNotReady
from backend.domain.iteration import iterate_method_change
from backend.domain.methods import (
    SOURCE_REGISTRY_DEFAULT,
    SOURCE_USER_OVERRIDE,
    is_user_choice_sentinel,
    resolve_default_method,
    resolve_method_tech_code,
    validate_method_id,
)
from backend.infrastructure.db.database import get_db
from backend.infrastructure.db.models import MethodConfig, Project
from backend.infrastructure.db.repositories.method_configs_repo import (
    list_method_configs,
    upsert_method_config,
)
from backend.infrastructure.registry import Registries, get_cache

router = APIRouter(prefix="/api/projects/{project_id}/methods", tags=["methods"])


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"project '{project_id}' not found",
        )
    return project


def _registries() -> Registries:
    return get_cache().get()


def _entry_from_registry(voice: dict) -> MethodConfigEntry:
    """Materialise a virtual entry for a voice that has no DB row yet."""
    default = resolve_default_method(voice)
    requires_choice = is_user_choice_sentinel(voice.get("default_method"))
    tech_code = (
        resolve_method_tech_code(default, _registries())
        if default is not None
        else None
    )
    return MethodConfigEntry(
        voice_id=voice["voice_id"],
        voice_statement=voice.get("statement"),
        voice_section=voice.get("section"),
        method_id=default,
        method_technical_code=tech_code,
        is_default=True,
        source=SOURCE_REGISTRY_DEFAULT,
        requires_user_choice=requires_choice,
        configured_at=None,
    )


def _entry_from_row(row: MethodConfig, voice: dict) -> MethodConfigEntry:
    return MethodConfigEntry(
        voice_id=row.voice_id,
        voice_statement=voice.get("statement"),
        voice_section=voice.get("section"),
        method_id=row.method_id,
        method_technical_code=row.method_technical_code,
        is_default=row.is_default,
        source=row.source,
        requires_user_choice=False,
        configured_at=row.configured_at,
    )


def _summarise(entries: list[MethodConfigEntry]) -> MethodConfigSummary:
    counts = {
        SOURCE_REGISTRY_DEFAULT: 0,
        SOURCE_USER_OVERRIDE: 0,
        "sector_pack": 0,
    }
    user_choice = 0
    for entry in entries:
        if entry.requires_user_choice:
            user_choice += 1
        if entry.source in counts:
            counts[entry.source] += 1
    return MethodConfigSummary(
        total=len(entries),
        registry_default=counts[SOURCE_REGISTRY_DEFAULT],
        user_override=counts[SOURCE_USER_OVERRIDE],
        sector_pack=counts["sector_pack"],
        user_choice_required=user_choice,
    )


@router.get("", response_model=MethodConfigList)
def get_methods(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
    statement: Annotated[
        str | None,
        Query(description="Optional filter on voice.statement (PL/BS/CF)"),
    ] = None,
) -> MethodConfigList:
    _get_project_or_404(db, project_id)
    reg = _registries()

    rows_by_voice: dict[str, MethodConfig] = {
        row.voice_id: row for row in list_method_configs(db, project_id)
    }

    entries: list[MethodConfigEntry] = []
    for voice_id, voice in reg.voices.items():
        if statement and voice.get("statement") != statement:
            continue
        row = rows_by_voice.get(voice_id)
        if row is None:
            entries.append(_entry_from_registry(voice))
        else:
            entries.append(_entry_from_row(row, voice))

    entries.sort(
        key=lambda e: (
            e.voice_statement or "",
            e.voice_section or "",
            e.voice_id,
        )
    )
    return MethodConfigList(
        project_id=project_id,
        count=len(entries),
        summary=_summarise(entries),
        items=entries,
    )


@router.put(
    "/{voice_id:path}",
    response_model=MethodConfigEntry,
    status_code=status.HTTP_200_OK,
)
def put_method(
    project_id: str,
    voice_id: str,
    payload: MethodUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> MethodConfigEntry:
    _get_project_or_404(db, project_id)
    reg = _registries()

    voice = reg.voices.get(voice_id)
    if voice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"voice '{voice_id}' not in voice_registry",
        )

    method_id = payload.method_id
    if not validate_method_id(method_id, reg):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"method '{method_id}' is neither a known method_id nor a "
                f"derived_rule_id"
            ),
        )

    registry_default = resolve_default_method(voice)
    is_default = method_id == registry_default
    source = SOURCE_REGISTRY_DEFAULT if is_default else SOURCE_USER_OVERRIDE
    tech_code = resolve_method_tech_code(method_id, reg)

    row = upsert_method_config(
        db,
        project_id=project_id,
        voice_id=voice_id,
        method_id=method_id,
        method_technical_code=tech_code,
        is_default=is_default,
        source=source,
    )
    db.flush()

    # Path 9.2: auto-trigger an engine re-run iff the project already
    # has a snapshot. ProjectNotReady (E0 not satisfied yet) is
    # surfaced as 422 — same convention as POST /run.
    try:
        iteration = iterate_method_change(project_id, db, _registries())
    except ProjectNotReady as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    db.commit()
    db.refresh(row)

    entry = _entry_from_row(row, voice)
    if iteration.snapshot is not None:
        entry = entry.model_copy(
            update={"triggered_snapshot_id": iteration.snapshot.id}
        )
    return entry


__all__ = ["router"]
