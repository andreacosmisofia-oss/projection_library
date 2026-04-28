"""Intake routes — Milestone M3 (``flows/01_data_intake.md``).

Implements Case 1 (gestionale) only. Re-upload performs a hard
replacement: the previous active balance is soft-deleted, a new
record + raw_voices are inserted in the same transaction.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Annotated, get_args

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from backend.api.schemas.balance import (
    BalanceLflPatch,
    BalanceLflResponse,
    BalanceUploadResponse,
    BalanceValidationItem,
    BalanceValidationReport,
    ParsedVoice,
    SourceType,
)
from backend.domain.intake import (
    BalanceValidationError,
    ParseError,
    parse_balance,
)
from backend.infrastructure.db.database import get_db
from backend.infrastructure.db.models import Balance, Project, RawVoice
from backend.infrastructure.db.repositories.balance_repo import (
    get_active_balance,
    get_balance_by_id,
    list_raw_voices,
    replace_active_balance,
    set_lfl_for_year,
    soft_delete_balance,
)

router = APIRouter(prefix="/api/projects/{project_id}/balance", tags=["intake"])

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB; warning threshold, not a hard cap


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"project '{project_id}' not found",
        )
    return project


def _voices_from_rows(rows: list[RawVoice]) -> list[ParsedVoice]:
    """Pivot long-format ``raw_voices`` rows back to ``ParsedVoice`` dicts."""
    grouped: dict[tuple[str, str | None], dict[str, float | None]] = defaultdict(dict)
    order: list[tuple[str, str | None]] = []
    for row in rows:
        key = (row.voice_user_label, row.voice_user_section)
        if key not in grouped:
            order.append(key)
        grouped[key][row.year] = row.amount
    return [
        ParsedVoice(user_label=label, user_section=section, values=grouped[(label, section)])
        for label, section in order
    ]


@router.post(
    "/upload",
    response_model=BalanceUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_balance(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File(description="Balance file (.xlsx/.xls/.csv)")],
    source_type: Annotated[
        str, Form(description="One of: gestionale, civilistico, both")
    ] = "gestionale",
) -> BalanceUploadResponse:
    _get_project_or_404(db, project_id)

    if source_type not in get_args(SourceType):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"invalid source_type '{source_type}'. "
                f"expected one of {list(get_args(SourceType))}"
            ),
        )
    if source_type != "gestionale":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "pilot v1.1 Milestone M3 supports only source_type='gestionale'. "
                "civilistico/both are scheduled for Milestone M3.b."
            ),
        )

    filename = file.filename or "upload"
    file_bytes = file.file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="uploaded file is empty",
        )

    soft_warning: BalanceValidationItem | None = None
    if len(file_bytes) > _MAX_UPLOAD_BYTES:
        soft_warning = BalanceValidationItem(
            code="LARGE_FILE",
            severity="warning",
            message=(
                f"file is {len(file_bytes)} bytes (>10 MB); "
                f"parsing may be slow"
            ),
            context={"size_bytes": len(file_bytes)},
        )

    try:
        parsed = parse_balance(
            file_bytes=file_bytes,
            filename=filename,
            source_type=source_type,  # type: ignore[arg-type]
        )
    except ParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except BalanceValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": str(exc),
                "validation": exc.parsed.validation.model_dump(),
            },
        ) from exc

    if soft_warning is not None:
        parsed.validation.warnings.insert(0, soft_warning)

    balance = replace_active_balance(db, project_id, parsed)
    db.commit()
    db.refresh(balance)

    return BalanceUploadResponse(
        balance_id=balance.id,
        source_type=parsed.source_type,
        raw_filename=balance.raw_filename,
        years_present=list(balance.years_present),
        voice_count=balance.voice_count,
        uploaded_at=balance.uploaded_at,
        voices=parsed.voices,
        validation=parsed.validation,
    )


@router.get("", response_model=BalanceUploadResponse)
def get_active_balance_endpoint(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> BalanceUploadResponse:
    _get_project_or_404(db, project_id)
    balance = get_active_balance(db, project_id)
    if balance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no active balance for project '{project_id}'",
        )
    rows = list_raw_voices(db, balance.id)
    return BalanceUploadResponse(
        balance_id=balance.id,
        source_type=balance.source_type,  # type: ignore[arg-type]
        raw_filename=balance.raw_filename,
        years_present=list(balance.years_present),
        voice_count=balance.voice_count,
        uploaded_at=balance.uploaded_at,
        voices=_voices_from_rows(rows),
        validation=BalanceValidationReport(),
    )


@router.delete("/{balance_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_balance(
    project_id: str,
    balance_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    _get_project_or_404(db, project_id)
    balance: Balance | None = get_balance_by_id(db, project_id, balance_id)
    if balance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"balance '{balance_id}' not found",
        )
    soft_delete_balance(db, balance)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{balance_id}/lfl", response_model=BalanceLflResponse)
def patch_lfl(
    project_id: str,
    balance_id: str,
    payload: BalanceLflPatch,
    db: Annotated[Session, Depends(get_db)],
) -> BalanceLflResponse:
    _get_project_or_404(db, project_id)
    balance = get_balance_by_id(db, project_id, balance_id)
    if balance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"balance '{balance_id}' not found",
        )
    if payload.year not in balance.years_present:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"year '{payload.year}' is not present in balance "
                f"(years_present={balance.years_present})"
            ),
        )
    updated = set_lfl_for_year(db, balance.id, payload.year, payload.lfl)
    db.commit()
    return BalanceLflResponse(
        balance_id=balance.id,
        year=payload.year,
        lfl=payload.lfl,
        rows_updated=updated,
    )


__all__ = ["router"]
