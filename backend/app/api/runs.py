from functools import lru_cache
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Path,
    status,
)
from openai import OpenAIError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import (
    InvalidExtractedRequirementsError,
    InvalidRetrievedEvidenceError,
)
from app.application_executor import (
    ApplicationGraphRunExecutor,
    RunExecutorConfigurationError,
)
from app.db import get_session, session_factory, settings
from app.models.agent_run import AgentRun
from app.models.artifact_record import ArtifactRecord
from app.models.run_event import RunEvent
from app.openai_provider import ProviderConfigurationError, ProviderResponseError
from app.providers import build_agent_provider
from app.rag.retrieval import RetrievalDocumentNotFoundError
from app.run_execution import (
    InvalidRunExecutionResultError,
    RunExecutionLeaseLostError,
)
from app.run_service import (
    AgentRunService,
    InvalidRunRequestError,
    RunAlreadyExecutingError,
    RunConflictError,
    RunDispatch,
    RunDocumentNotIngestedError,
    RunExecutorMismatchError,
    RunNotResumableError,
    RunResourceNotFoundError,
)
from app.schemas.run import RunArtifactRead, RunCreate, RunEventRead, RunRead

_EXECUTION_FAILURES = (
    InvalidRunExecutionResultError,
    RunExecutionLeaseLostError,
    RunExecutorConfigurationError,
    ProviderConfigurationError,
    ProviderResponseError,
    OpenAIError,
    SQLAlchemyError,
    InvalidExtractedRequirementsError,
    InvalidRetrievedEvidenceError,
    RetrievalDocumentNotFoundError,
    RunExecutorMismatchError,
)


router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}",
    tags=["runs"],
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

IdempotencyKeyHeader = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=200,
    ),
]


@lru_cache(maxsize=1)
def _build_default_run_service() -> AgentRunService:
    provider = build_agent_provider(settings)
    executor = ApplicationGraphRunExecutor(
        session_factory=session_factory,
        provider=provider,
        provider_retry_max_attempts=settings.provider_retry_max_attempts,
        provider_retry_initial_delay_seconds=(
            settings.provider_retry_initial_delay_seconds
        ),
    )
    return AgentRunService(
        session_factory=session_factory,
        executor=executor,
    )


def get_run_service() -> AgentRunService:
    try:
        return _build_default_run_service()
    except (ProviderConfigurationError, OpenAIError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Run service unavailable",
        ) from error


async def close_default_run_service() -> None:
    if _build_default_run_service.cache_info().currsize == 0:
        return
    service = _build_default_run_service()
    try:
        await service.aclose()
    finally:
        _build_default_run_service.cache_clear()


RunServiceDependency = Annotated[
    AgentRunService,
    Depends(get_run_service),
]


async def _execute_in_background(
    service: AgentRunService,
    dispatch: RunDispatch,
) -> None:
    try:
        await service.execute_dispatch(dispatch)
    except Exception:  # noqa: BLE001 -- public background-task exception boundary
        # The service has already persisted a sanitized terminal failure. The
        # accepted HTTP response must not be replaced by a private exception.
        return


async def _read_run(
    *,
    session: AsyncSession,
    workspace_id: str,
    run_id: UUID,
) -> RunRead:
    try:
        rows = (
            await session.execute(
                select(AgentRun, RunEvent, ArtifactRecord)
                .outerjoin(RunEvent, RunEvent.run_id == AgentRun.id)
                .outerjoin(ArtifactRecord, ArtifactRecord.run_id == AgentRun.id)
                .where(
                    AgentRun.id == run_id,
                    AgentRun.workspace_id == workspace_id,
                )
                .order_by(RunEvent.sequence)
            )
        ).all()
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Run service unavailable",
        ) from error

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    run = rows[0][0]
    events = [event for _, event, _ in rows if event is not None]
    artifact = next(
        (record for _, _, record in rows if record is not None),
        None,
    )
    return _to_run_read(run, events=events, artifact=artifact)


def _to_run_read(
    run: AgentRun,
    *,
    events: list[RunEvent],
    artifact: ArtifactRecord | None,
) -> RunRead:
    return RunRead(
        id=run.id,
        workspace_id=run.workspace_id,
        job_id=run.job_id,
        idempotency_key=run.idempotency_key,
        document_ids=[UUID(value) for value in run.document_ids],
        status=run.status,  # type: ignore[arg-type]
        provider=run.provider,
        model=run.model,
        current_node=run.current_node,
        revision_count=run.revision_count,
        attempt_count=run.attempt_count,
        retryable=run.retryable,
        error_code=run.error_code,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        lease_expires_at=run.lease_expires_at,
        events=[RunEventRead.model_validate(event) for event in events],
        artifact=(
            None if artifact is None else RunArtifactRead.model_validate(artifact)
        ),
    )


def _raise_start_error(error: Exception) -> NoReturn:
    if isinstance(error, InvalidRunRequestError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid run request",
        ) from error
    if isinstance(error, RunResourceNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run input not found",
        ) from error
    if isinstance(error, (RunConflictError, RunDocumentNotIngestedError)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run request conflicts with existing state",
        ) from error
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Run execution failed",
    ) from error


@router.post(
    "/jobs/{job_id}/runs",
    response_model=RunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_run(
    background_tasks: BackgroundTasks,
    workspace_id: WorkspaceId,
    job_id: UUID,
    payload: RunCreate,
    idempotency_key: IdempotencyKeyHeader,
    service: RunServiceDependency,
    session: SessionDependency,
) -> RunRead:
    try:
        dispatch = await service.prepare_run(
            workspace_id=workspace_id,
            job_id=job_id,
            document_ids=payload.document_ids,
            idempotency_key=idempotency_key,
        )
    except (
        InvalidRunRequestError,
        RunResourceNotFoundError,
        RunConflictError,
        RunDocumentNotIngestedError,
    ) as error:
        _raise_start_error(error)
    except RunAlreadyExecutingError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run is already executing",
        ) from error
    except _EXECUTION_FAILURES as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Run execution failed",
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Run execution failed",
        ) from error

    background_tasks.add_task(_execute_in_background, service, dispatch)
    return await _read_run(
        session=session,
        workspace_id=workspace_id,
        run_id=dispatch.run_id,
    )


@router.get(
    "/runs/{run_id}",
    response_model=RunRead,
)
async def get_run(
    workspace_id: WorkspaceId,
    run_id: UUID,
    session: SessionDependency,
) -> RunRead:
    return await _read_run(
        session=session,
        workspace_id=workspace_id,
        run_id=run_id,
    )


@router.post(
    "/runs/{run_id}/resume",
    response_model=RunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_run(
    background_tasks: BackgroundTasks,
    workspace_id: WorkspaceId,
    run_id: UUID,
    service: RunServiceDependency,
    session: SessionDependency,
) -> RunRead:
    try:
        dispatch = await service.prepare_resume(
            workspace_id=workspace_id,
            run_id=run_id,
        )
    except RunResourceNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        ) from error
    except (RunNotResumableError, RunAlreadyExecutingError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run cannot be resumed",
        ) from error
    except _EXECUTION_FAILURES as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Run execution failed",
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Run execution failed",
        ) from error

    background_tasks.add_task(_execute_in_background, service, dispatch)
    return await _read_run(
        session=session,
        workspace_id=workspace_id,
        run_id=run_id,
    )
