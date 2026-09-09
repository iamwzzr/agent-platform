from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import and_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app import db
from app.api.jobs import SessionDependency, WorkspaceId
from app.models.agent_run import AgentRun
from app.models.artifact_record import ArtifactRecord
from app.models.job import Job
from app.providers import DeterministicMockProvider
from app.schemas.artifact import ApplicationArtifact, ArtifactValidation
from app.schemas.overview import (
    OverviewConfiguration,
    OverviewUsage,
    WorkspaceOverviewRead,
)

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/overview",
    tags=["overview"],
)


def _configuration() -> OverviewConfiguration:
    settings = db.settings
    return OverviewConfiguration(
        provider=settings.llm_provider,
        model=(
            DeterministicMockProvider.model_name
            if settings.llm_provider == "mock"
            else (settings.openai_model or "").strip()
        ),
        max_revisions=settings.agent_max_revisions,
        provider_retry_max_attempts=settings.provider_retry_max_attempts,
        provider_retry_initial_delay_seconds=(
            settings.provider_retry_initial_delay_seconds
        ),
        retrieval_method="deterministic_sparse_cosine",
        # ApplicationGraphRunExecutor uses retrieve_chunks' default top_k.
        retrieval_top_k=5,
    )


async def _usage(session: AsyncSession, workspace_id: str) -> OverviewUsage:
    # One SELECT keeps run and material totals on the same database snapshot,
    # including on SQLite's legacy transaction mode. Never join run events.
    rows = await session.stream(
        select(
            Job.id,
            AgentRun.id,
            AgentRun.status,
            AgentRun.provider,
            ArtifactRecord.content,
            ArtifactRecord.validation,
        )
        .select_from(Job)
        .outerjoin(
            AgentRun,
            and_(
                AgentRun.job_id == Job.id,
                AgentRun.workspace_id == Job.workspace_id,
            ),
        )
        .outerjoin(
            ArtifactRecord,
            and_(
                ArtifactRecord.run_id == AgentRun.id,
                AgentRun.status == "succeeded",
            ),
        )
        .where(Job.workspace_id == workspace_id)
        .execution_options(yield_per=100)
    )
    usage = OverviewUsage()
    job_ids: set[UUID] = set()
    jobs_with_runs: set[UUID] = set()
    run_ids: set[UUID] = set()
    published_job_ids: set[UUID] = set()
    try:
        async for (
            job_id,
            run_id,
            run_status,
            provider,
            content,
            stored_validation,
        ) in rows:
            job_ids.add(job_id)
            if run_id is None or run_id in run_ids:
                continue
            run_ids.add(run_id)
            jobs_with_runs.add(job_id)
            usage.runs += 1
            usage.succeeded_runs += int(run_status == "succeeded")
            usage.validation_failed_runs += int(run_status == "validation_failed")
            usage.failed_runs += int(run_status == "failed")
            usage.active_runs += int(run_status in ("queued", "running"))
            usage.mock_runs += int(provider == "mock")
            usage.openai_runs += int(provider == "openai")
            usage.other_provider_runs += int(provider not in ("mock", "openai"))
            if (
                not isinstance(stored_validation, dict)
                or stored_validation.get("passed") is not True
            ):
                continue
            try:
                ArtifactValidation.model_validate(stored_validation)
                artifact = ApplicationArtifact.model_validate(content)
            except (ValidationError, TypeError, ValueError):
                # Malformed legacy records are excluded, without logging content.
                continue
            if artifact.run_id != run_id:
                continue

            usage.published_artifacts += 1
            published_job_ids.add(job_id)
            usage.resume_bullets += len(artifact.resume_bullets)
            usage.gaps += len(artifact.gaps)
            usage.cover_letters += int(artifact.cover_letter is not None)
            usage.artifacts_with_resume_bullets += int(bool(artifact.resume_bullets))
            usage.gap_only_artifacts += int(
                bool(artifact.gaps)
                and not artifact.resume_bullets
                and not artifact.claims
                and artifact.cover_letter is None
            )
    finally:
        await rows.close()
    usage.saved_jobs = len(job_ids)
    usage.jobs_with_runs = len(jobs_with_runs)
    usage.jobs_with_published_artifacts = len(published_job_ids)
    return usage


@router.get("", response_model=WorkspaceOverviewRead)
async def get_workspace_overview(
    workspace_id: WorkspaceId,
    session: SessionDependency,
) -> WorkspaceOverviewRead:
    """Read current deployment configuration and persisted workspace usage."""
    try:
        usage = await _usage(session, workspace_id)
    except (SQLAlchemyError, ValueError, TypeError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workspace overview unavailable",
        ) from error
    return WorkspaceOverviewRead(
        workspace_id=workspace_id,
        generated_at=datetime.now(UTC),
        configuration=_configuration(),
        usage=usage,
    )
