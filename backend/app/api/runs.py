from datetime import UTC, datetime
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
from pydantic import ValidationError
from sqlalchemy import and_, select
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
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
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
from app.schemas.artifact import ApplicationArtifact, ArtifactValidation
from app.schemas.run import (
    CitationSourceRead,
    RunArtifactRead,
    RunCreate,
    RunEventRead,
    RunRead,
)

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
        _raise_read_error(error)

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
    try:
        artifact_read = await _to_artifact_read(
            session=session,
            workspace_id=workspace_id,
            artifact=artifact,
        )
        return _to_run_read(run, events=events, artifact=artifact_read)
    except (SQLAlchemyError, ValidationError, TypeError, ValueError) as error:
        _raise_read_error(error)


async def _to_artifact_read(
    *,
    session: AsyncSession,
    workspace_id: str,
    artifact: ArtifactRecord | None,
) -> RunArtifactRead | None:
    if artifact is None:
        return None

    content = ApplicationArtifact.model_validate(artifact.content)
    validation = ArtifactValidation.model_validate(artifact.validation)
    citation_sources = await _read_citation_sources(
        session=session,
        workspace_id=workspace_id,
        content=content,
        validation=validation,
    )
    return RunArtifactRead(
        id=artifact.id,
        run_id=artifact.run_id,
        content=content,
        validation=validation,
        citation_sources=citation_sources,
        created_at=artifact.created_at,
    )


async def _read_citation_sources(
    *,
    session: AsyncSession,
    workspace_id: str,
    content: ApplicationArtifact,
    validation: ArtifactValidation,
) -> list[CitationSourceRead]:
    if not validation.passed or not content.citations:
        return []

    citation_pairs = list(
        dict.fromkeys(
            (citation.document_id, citation.chunk_id) for citation in content.citations
        )
    )
    chunk_ids = [chunk_id for _, chunk_id in citation_pairs]
    rows = (
        await session.execute(
            select(DocumentChunk, Document.name)
            .join(
                Document,
                and_(
                    Document.id == DocumentChunk.document_id,
                    Document.workspace_id == DocumentChunk.workspace_id,
                ),
            )
            .where(
                DocumentChunk.workspace_id == workspace_id,
                Document.workspace_id == workspace_id,
                DocumentChunk.id.in_(chunk_ids),
            )
        )
    ).all()
    sources_by_pair = {
        (chunk.document_id, chunk.id): CitationSourceRead(
            document_id=chunk.document_id,
            document_name=document_name,
            chunk_id=chunk.id,
            position=chunk.position,
            excerpt=chunk.content,
        )
        for chunk, document_name in rows
    }
    return [sources_by_pair[pair] for pair in citation_pairs if pair in sources_by_pair]


def _to_run_read(
    run: AgentRun,
    *,
    events: list[RunEvent],
    artifact: RunArtifactRead | None,
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
        can_resume=_can_resume(run),
        terminal_validation=_terminal_validation(run, events),
        error_code=run.error_code,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        lease_expires_at=run.lease_expires_at,
        events=[RunEventRead.model_validate(event) for event in events],
        artifact=artifact,
    )


def _can_resume(run: AgentRun) -> bool:
    if run.status == "failed":
        return run.retryable
    if run.status != "running" or run.lease_expires_at is None:
        return False

    now = datetime.now(UTC)
    comparable_now = (
        now if run.lease_expires_at.tzinfo is not None else now.replace(tzinfo=None)
    )
    return run.lease_expires_at <= comparable_now


def _terminal_validation(
    run: AgentRun,
    events: list[RunEvent],
) -> ArtifactValidation | None:
    if run.status != "validation_failed":
        return None
    for event in reversed(events):
        if event.kind != "validation_failed":
            continue
        if not isinstance(event.data, dict):
            raise TypeError("Invalid persisted run event data")
        raw_validation = event.data.get("validation")
        if raw_validation is None:
            return None
        return ArtifactValidation.model_validate(raw_validation)
    return None


def _raise_read_error(error: Exception) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Run service unavailable",
    ) from error


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
