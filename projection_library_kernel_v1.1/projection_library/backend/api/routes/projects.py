"""CRUD endpoints for the ``projects`` resource (Milestone M2).

Soft delete is the default: ``DELETE`` sets ``deleted_at`` and the row
disappears from list/detail/patch endpoints, but stays in the table.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.schemas.projects import (
    ProjectCreate,
    ProjectList,
    ProjectResponse,
    ProjectUpdate,
)
from backend.infrastructure.db.database import get_db
from backend.infrastructure.db.models import Project

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _get_active_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"project '{project_id}' not found",
        )
    return project


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Annotated[Session, Depends(get_db)],
) -> Project:
    project = Project(**payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=ProjectList)
def list_projects(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectList:
    stmt = (
        select(Project)
        .where(Project.deleted_at.is_(None))
        .order_by(Project.created_at.desc(), Project.id.desc())
        .offset(offset)
        .limit(limit)
    )
    items = db.execute(stmt).scalars().all()
    count_stmt = select(Project).where(Project.deleted_at.is_(None))
    total = len(db.execute(count_stmt).scalars().all())
    return ProjectList(
        count=total,
        items=[ProjectResponse.model_validate(p) for p in items],
    )


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> Project:
    return _get_active_or_404(db, project_id)


@router.patch("/{project_id}", response_model=ProjectResponse)
def patch_project(
    project_id: str,
    payload: ProjectUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> Project:
    project = _get_active_or_404(db, project_id)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    project = _get_active_or_404(db, project_id)
    project.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
