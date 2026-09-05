from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.job import Job
from app.schemas.job import JobCreate, JobRead

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/jobs",
    tags=["jobs"],
)

SessionDependency = Annotated[
    AsyncSession,
    Depends(get_session),
]

WorkspaceId = Annotated[
    str,
    Path(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    ),
]


@router.post(
    "",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_job(
    workspace_id: WorkspaceId,
    payload: JobCreate,
    session: SessionDependency,
) -> Job:
    job = Job(
        workspace_id=workspace_id,
        title=payload.title,
        description=payload.description,
    )

    session.add(job)
    await session.commit()
    await session.refresh(job)

    return job


@router.get(
    "/{job_id}",
    response_model=JobRead,
)
async def get_job(
    workspace_id: WorkspaceId,
    job_id: UUID,
    session: SessionDependency,
) -> Job:
    result = await session.execute(
        select(Job).where(
            Job.id == job_id,
            Job.workspace_id == workspace_id,
        )
    )
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    return job
