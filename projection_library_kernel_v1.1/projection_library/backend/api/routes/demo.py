"""Demo route — Milestone M13.

One-click sample-project loader. Uploads the bundled
``tier2_industrial_clean.xlsx`` balance, applies a hardcoded mapping
table, materialises registry-default method configs, and runs the
engine end-to-end so the caller gets back a project + snapshot ready
to render in the dashboard.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.domain.demo import load_sample_project
from backend.domain.engine.executor import ProjectNotReady
from backend.domain.intake import BalanceValidationError, ParseError
from backend.infrastructure.db.database import get_db
from backend.infrastructure.registry import Registries, get_cache

router = APIRouter(prefix="/api/demo", tags=["demo"])


class DemoLoadResponse(BaseModel):
    project_id: str
    snapshot_id: str
    balance_id: str
    voice_count: int
    mapping_count: int
    method_config_count: int


def _registries() -> Registries:
    return get_cache().get()


@router.post(
    "/load-sample",
    response_model=DemoLoadResponse,
    status_code=status.HTTP_201_CREATED,
)
def load_sample(
    db: Annotated[Session, Depends(get_db)],
) -> DemoLoadResponse:
    try:
        result = load_sample_project(db, _registries())
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except (ParseError, BalanceValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except ProjectNotReady as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    db.commit()
    return DemoLoadResponse(
        project_id=result.project_id,
        snapshot_id=result.snapshot_id,
        balance_id=result.balance_id,
        voice_count=result.voice_count,
        mapping_count=result.mapping_count,
        method_config_count=result.method_config_count,
    )


__all__ = ["router"]
