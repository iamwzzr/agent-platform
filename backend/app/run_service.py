import asyncio
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from inspect import isawaitable
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.agent_run import AgentRun
from app.models.artifact_record import ArtifactRecord
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.job import Job
from app.models.run_event import RunEvent
from app.providers import classify_provider_error
from app.run_execution import (
    InvalidRunExecutionResultError,
    RunExecutionLeaseLostError,
    RunExecutionResult,
)
from app.schemas.artifact import (
    ApplicationArtifact,
    ArtifactValidation,
    Evidence,
    Requirement,
)


class InvalidRunRequestError(ValueError):
    """Raised when a run request violates the input contract."""


class RunResourceNotFoundError(LookupError):
    """Raised when a run or its inputs are not visible in the workspace."""


class RunDocumentNotIngestedError(RuntimeError):
    """Raised when a selected document has no stored chunks."""


class RunConflictError(RuntimeError):
    """Raised when an idempotency key is reused for a different request."""


class RunNotResumableError(RuntimeError):
    """Raised when a run is terminal or failed permanently."""


class RunAlreadyExecutingError(RuntimeError):
    """Raised when another worker claimed the same run."""


class RunExecutorMismatchError(RuntimeError):
    """Raised when the configured executor cannot continue a persisted run."""


RunExecutor = Callable[[UUID, UUID], Awaitable[RunExecutionResult]]


@dataclass(frozen=True, slots=True)
class RunDispatch:
    """An internal, fenced claim that can safely execute after an HTTP response."""

    run_id: UUID
    execution_token: UUID | None


class AgentRunService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        executor: RunExecutor,
        execution_lease_seconds: float = 900,
    ) -> None:
        if not 1 <= execution_lease_seconds <= 86_400:
            raise ValueError("execution_lease_seconds must be between 1 and 86400")
        self._session_factory = session_factory
        self._executor = executor
        self._execution_lease = timedelta(seconds=execution_lease_seconds)

    async def aclose(self) -> None:
        close = getattr(self._executor, "aclose", None)
        if close is None:
            return
        result = close()
        if isawaitable(result):
            await result

    @staticmethod
    async def _next_event_sequence(
        session: AsyncSession,
        run_id: UUID,
    ) -> int:
        latest_sequence = await session.scalar(
            select(func.max(RunEvent.sequence)).where(RunEvent.run_id == run_id)
        )
        return 0 if latest_sequence is None else latest_sequence + 1

    async def _begin_execution(
        self,
        run_id: UUID,
        *,
        expected_status: str,
        event_kind: str,
        require_retryable: bool = False,
        require_expired_lease: bool = False,
    ) -> UUID:
        async with self._session_factory() as session:
            now = datetime.now(UTC)
            execution_token = uuid4()
            conditions = [
                AgentRun.id == run_id,
                AgentRun.status == expected_status,
            ]
            if require_retryable:
                conditions.append(AgentRun.retryable.is_(True))
            if require_expired_lease:
                conditions.extend(
                    [
                        AgentRun.lease_expires_at.is_not(None),
                        AgentRun.lease_expires_at <= now,
                    ]
                )
            claim = await session.execute(
                update(AgentRun)
                .where(*conditions)
                .values(
                    status="running",
                    started_at=func.coalesce(AgentRun.started_at, now),
                    finished_at=None,
                    retryable=False,
                    error_code=None,
                    attempt_count=AgentRun.attempt_count + 1,
                    lease_expires_at=now + self._execution_lease,
                    execution_token=execution_token,
                )
            )
            if claim.rowcount != 1:
                raise RunAlreadyExecutingError("Agent run was already claimed")

            run = await session.get(AgentRun, run_id)
            if run is None:
                raise RunResourceNotFoundError("Agent run was not found")
            session.add(
                RunEvent(
                    run_id=run_id,
                    sequence=await self._next_event_sequence(session, run_id),
                    kind=event_kind,
                    data={"attempt": run.attempt_count},
                )
            )
            await session.commit()
        return execution_token

    async def _transition_terminal(
        self,
        run_id: UUID,
        *,
        execution_token: UUID,
        next_status: str,
        event_data: dict[str, object] | None = None,
    ) -> None:
        async with self._session_factory() as session:
            transition = await session.execute(
                update(AgentRun)
                .where(
                    AgentRun.id == run_id,
                    AgentRun.status == "running",
                    AgentRun.execution_token == execution_token,
                )
                .values(
                    status=next_status,
                    finished_at=datetime.now(UTC),
                    lease_expires_at=None,
                    execution_token=None,
                )
            )
            if transition.rowcount != 1:
                raise RunExecutionLeaseLostError(
                    "Run execution lease is no longer owned by this worker"
                )
            session.add(
                RunEvent(
                    run_id=run_id,
                    sequence=await self._next_event_sequence(session, run_id),
                    kind=next_status,
                    data={} if event_data is None else dict(event_data),
                )
            )
            await session.commit()

    async def _mark_failed(
        self,
        run_id: UUID,
        *,
        execution_token: UUID,
        reason_code: str,
        retryable: bool,
    ) -> None:
        async with self._session_factory() as session:
            transition = await session.execute(
                update(AgentRun)
                .where(
                    AgentRun.id == run_id,
                    AgentRun.status == "running",
                    AgentRun.execution_token == execution_token,
                )
                .values(
                    status="failed",
                    finished_at=datetime.now(UTC),
                    retryable=retryable,
                    error_code=reason_code,
                    lease_expires_at=None,
                    execution_token=None,
                )
            )
            if transition.rowcount != 1:
                raise RunExecutionLeaseLostError(
                    "Run execution lease is no longer owned by this worker"
                )
            session.add(
                RunEvent(
                    run_id=run_id,
                    sequence=await self._next_event_sequence(session, run_id),
                    kind="failed",
                    data={
                        "reason_code": reason_code,
                        "retryable": retryable,
                    },
                )
            )
            await session.commit()

    async def _complete_success(
        self,
        run_id: UUID,
        *,
        execution_token: UUID,
        artifact: ApplicationArtifact,
        validation: ArtifactValidation,
    ) -> None:
        async with self._session_factory() as session:
            transition = await session.execute(
                update(AgentRun)
                .where(
                    AgentRun.id == run_id,
                    AgentRun.status == "running",
                    AgentRun.execution_token == execution_token,
                )
                .values(
                    status="succeeded",
                    finished_at=datetime.now(UTC),
                    retryable=False,
                    error_code=None,
                    lease_expires_at=None,
                    execution_token=None,
                )
            )
            if transition.rowcount != 1:
                raise RunExecutionLeaseLostError(
                    "Run execution lease is no longer owned by this worker"
                )
            session.add_all(
                [
                    ArtifactRecord(
                        run_id=run_id,
                        content=artifact.model_dump(mode="json"),
                        validation=validation.model_dump(mode="json"),
                    ),
                    RunEvent(
                        run_id=run_id,
                        sequence=await self._next_event_sequence(session, run_id),
                        kind="succeeded",
                    ),
                ]
            )
            await session.commit()

    async def _validate_inputs(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        job_id: UUID,
        requested_document_ids: set[UUID],
    ) -> None:
        visible_job_id = await session.scalar(
            select(Job.id).where(
                Job.id == job_id,
                Job.workspace_id == workspace_id,
            )
        )
        if visible_job_id is None:
            raise RunResourceNotFoundError("Run inputs were not found")

        visible_document_ids = set(
            await session.scalars(
                select(Document.id).where(
                    Document.workspace_id == workspace_id,
                    Document.id.in_(requested_document_ids),
                )
            )
        )
        if visible_document_ids != requested_document_ids:
            raise RunResourceNotFoundError("Run inputs were not found")

        ingested_document_ids = set(
            (
                await session.scalars(
                    select(DocumentChunk.document_id)
                    .where(
                        DocumentChunk.workspace_id == workspace_id,
                        DocumentChunk.document_id.in_(requested_document_ids),
                    )
                    .distinct()
                )
            ).all()
        )
        if ingested_document_ids != requested_document_ids:
            raise RunDocumentNotIngestedError("Run documents have not been ingested")

    async def _heartbeat(
        self,
        run_id: UUID,
        execution_token: UUID,
        stop: asyncio.Event,
    ) -> None:
        interval_seconds = max(0.1, self._execution_lease.total_seconds() / 3)
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except TimeoutError:
                pass
            else:
                return
            try:
                async with self._session_factory() as session:
                    heartbeat = await session.execute(
                        update(AgentRun)
                        .where(
                            AgentRun.id == run_id,
                            AgentRun.status == "running",
                            AgentRun.execution_token == execution_token,
                        )
                        .values(
                            lease_expires_at=(datetime.now(UTC) + self._execution_lease)
                        )
                    )
                    await session.commit()
            except SQLAlchemyError:
                if stop.is_set():
                    return
                raise
            if stop.is_set():
                return
            if heartbeat.rowcount != 1:
                raise RunExecutionLeaseLostError(
                    "Run execution lease is no longer owned by this worker"
                )

    async def _execute(self, run_id: UUID, execution_token: UUID) -> None:
        heartbeat_stop = asyncio.Event()
        execution_task = asyncio.create_task(
            self._execute_claimed(
                run_id,
                execution_token,
                heartbeat_stop,
            )
        )
        heartbeat_task = asyncio.create_task(
            self._heartbeat(run_id, execution_token, heartbeat_stop)
        )
        try:
            done, _ = await asyncio.wait(
                {execution_task, heartbeat_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if execution_task in done:
                await execution_task
                return

            try:
                await heartbeat_task
            except RunExecutionLeaseLostError:
                execution_task.cancel()
                await asyncio.gather(execution_task, return_exceptions=True)
                raise
            except SQLAlchemyError:
                execution_task.cancel()
                await asyncio.gather(execution_task, return_exceptions=True)
                with suppress(SQLAlchemyError, RunExecutionLeaseLostError):
                    await self._mark_failed(
                        run_id,
                        execution_token=execution_token,
                        reason_code="checkpoint_persistence_error",
                        retryable=True,
                    )
                raise
            else:
                await execution_task
        except asyncio.CancelledError:
            heartbeat_stop.set()
            execution_task.cancel()
            heartbeat_task.cancel()
            await asyncio.gather(
                execution_task,
                heartbeat_task,
                return_exceptions=True,
            )
            with suppress(SQLAlchemyError, RunExecutionLeaseLostError):
                await asyncio.shield(self._mark_interrupted(run_id, execution_token))
            raise
        finally:
            heartbeat_stop.set()
            execution_task.cancel()
            heartbeat_task.cancel()
            await asyncio.gather(
                execution_task,
                heartbeat_task,
                return_exceptions=True,
            )

    async def _mark_interrupted(
        self,
        run_id: UUID,
        execution_token: UUID,
    ) -> None:
        async with self._session_factory() as session:
            transition = await session.execute(
                update(AgentRun)
                .where(
                    AgentRun.id == run_id,
                    AgentRun.status == "running",
                    AgentRun.execution_token == execution_token,
                )
                .values(
                    status="failed",
                    finished_at=datetime.now(UTC),
                    retryable=True,
                    error_code="execution_interrupted",
                    lease_expires_at=None,
                    execution_token=None,
                )
            )
            if transition.rowcount != 1:
                return
            session.add(
                RunEvent(
                    run_id=run_id,
                    sequence=await self._next_event_sequence(session, run_id),
                    kind="failed",
                    data={
                        "reason_code": "execution_interrupted",
                        "retryable": True,
                    },
                )
            )
            await session.commit()

    async def _execute_claimed(
        self,
        run_id: UUID,
        execution_token: UUID,
        heartbeat_stop: asyncio.Event,
    ) -> None:
        try:
            async with self._session_factory() as session:
                workspace_id = await session.scalar(
                    select(AgentRun.workspace_id).where(
                        AgentRun.id == run_id,
                        AgentRun.status == "running",
                        AgentRun.execution_token == execution_token,
                    )
                )
            if workspace_id is None:
                raise RunExecutionLeaseLostError(
                    "Run execution lease is no longer owned by this worker"
                )
            raw_execution_result = await self._executor(run_id, execution_token)
            execution_result = self._validate_execution_result(
                raw_execution_result,
                run_id,
                workspace_id,
            )
        except RunExecutionLeaseLostError:
            raise
        except InvalidRunExecutionResultError:
            heartbeat_stop.set()
            await self._mark_failed(
                run_id,
                execution_token=execution_token,
                reason_code="invalid_executor_result",
                retryable=False,
            )
            raise
        except SQLAlchemyError:
            heartbeat_stop.set()
            await self._mark_failed(
                run_id,
                execution_token=execution_token,
                reason_code="checkpoint_persistence_error",
                retryable=True,
            )
            raise
        except Exception as error:
            failure = classify_provider_error(error)
            heartbeat_stop.set()
            await self._mark_failed(
                run_id,
                execution_token=execution_token,
                reason_code=failure.reason_code,
                retryable=failure.retryable,
            )
            raise

        heartbeat_stop.set()
        try:
            if execution_result.terminal_status == "validation_failed":
                await self._transition_terminal(
                    run_id,
                    execution_token=execution_token,
                    next_status="validation_failed",
                    event_data={
                        "reason_code": "validation_failed",
                        "validation": execution_result.validation.model_dump(
                            mode="json"
                        ),
                    },
                )
                return

            artifact = execution_result.artifact
            if artifact is None:
                raise InvalidRunExecutionResultError(
                    "Successful run execution requires an artifact"
                )
            await self._complete_success(
                run_id,
                execution_token=execution_token,
                artifact=artifact,
                validation=execution_result.validation,
            )
        except RunExecutionLeaseLostError:
            raise
        except SQLAlchemyError:
            with suppress(SQLAlchemyError, RunExecutionLeaseLostError):
                await self._mark_failed(
                    run_id,
                    execution_token=execution_token,
                    reason_code="persistence_error",
                    retryable=True,
                )
            raise

    @staticmethod
    def _validate_execution_result(
        execution_result: object,
        run_id: UUID,
        workspace_id: str,
    ) -> RunExecutionResult:
        if not isinstance(execution_result, RunExecutionResult):
            raise InvalidRunExecutionResultError(
                "Run executor returned an invalid result"
            )
        try:
            artifact = (
                None
                if execution_result.artifact is None
                else ApplicationArtifact.model_validate(
                    execution_result.artifact.model_dump(mode="python")
                )
            )
            validation = ArtifactValidation.model_validate(
                execution_result.validation.model_dump(mode="python")
            )
            trusted_requirements = tuple(
                Requirement.model_validate(requirement.model_dump(mode="python"))
                for requirement in execution_result.trusted_requirements
            )
            retrieved_evidence = tuple(
                Evidence.model_validate(evidence.model_dump(mode="python"))
                for evidence in execution_result.retrieved_evidence
            )
            snapshot = RunExecutionResult(
                run_id=execution_result.run_id,
                workspace_id=execution_result.workspace_id,
                terminal_status=execution_result.terminal_status,
                artifact=artifact,
                validation=validation,
                trusted_requirements=trusted_requirements,
                retrieved_evidence=retrieved_evidence,
            )
        except (AttributeError, TypeError, ValidationError) as error:
            raise InvalidRunExecutionResultError(
                "Run executor returned an invalid result"
            ) from error
        if snapshot.run_id != run_id:
            raise InvalidRunExecutionResultError(
                "Run execution result does not match the run"
            )
        if snapshot.workspace_id != workspace_id:
            raise InvalidRunExecutionResultError(
                "Run execution result does not match the workspace"
            )
        if snapshot.terminal_status == "succeeded" and (
            snapshot.artifact is None or snapshot.artifact.run_id != run_id
        ):
            raise InvalidRunExecutionResultError(
                "Run execution artifact does not match the run"
            )
        return snapshot

    async def start_run(
        self,
        *,
        workspace_id: str,
        job_id: UUID,
        document_ids: Sequence[UUID],
        idempotency_key: str,
    ) -> UUID:
        dispatch = await self.prepare_run(
            workspace_id=workspace_id,
            job_id=job_id,
            document_ids=document_ids,
            idempotency_key=idempotency_key,
        )
        await self.execute_dispatch(dispatch)
        return dispatch.run_id

    async def prepare_run(
        self,
        *,
        workspace_id: str,
        job_id: UUID,
        document_ids: Sequence[UUID],
        idempotency_key: str,
    ) -> RunDispatch:
        """Persist and claim a run without waiting for provider execution."""
        requested_document_ids = set(document_ids)
        normalized_document_ids = sorted(
            str(document_id) for document_id in requested_document_ids
        )
        normalized_idempotency_key = idempotency_key.strip()
        if not normalized_document_ids:
            raise InvalidRunRequestError("At least one document is required")
        if not normalized_idempotency_key:
            raise InvalidRunRequestError("Idempotency key must not be blank")

        claim_status: str | None = None
        require_expired_lease = False
        async with self._session_factory() as session:
            existing_run = await session.scalar(
                select(AgentRun).where(
                    AgentRun.workspace_id == workspace_id,
                    AgentRun.idempotency_key == normalized_idempotency_key,
                )
            )
            if existing_run is not None:
                self._ensure_same_request(
                    existing_run,
                    job_id=job_id,
                    document_ids=normalized_document_ids,
                )
                run_id = existing_run.id
                if existing_run.status == "queued":
                    self._ensure_executor_compatible(existing_run)
                    claim_status = "queued"
                elif existing_run.status == "running" and self._lease_is_expired(
                    existing_run.lease_expires_at
                ):
                    self._ensure_executor_compatible(existing_run)
                    claim_status = "running"
                    require_expired_lease = True
            else:
                await self._validate_inputs(
                    session,
                    workspace_id=workspace_id,
                    job_id=job_id,
                    requested_document_ids=requested_document_ids,
                )
                run = AgentRun(
                    workspace_id=workspace_id,
                    job_id=job_id,
                    document_ids=normalized_document_ids,
                    idempotency_key=normalized_idempotency_key,
                    provider=self._executor_identity(
                        "provider_name",
                        "mock",
                    ),
                    model=self._executor_identity(
                        "model_name",
                        "deterministic-mock-v1",
                    ),
                )
                session.add(run)
                try:
                    await session.flush()
                    run_id = run.id
                    session.add(
                        RunEvent(
                            run_id=run_id,
                            sequence=0,
                            kind="queued",
                        )
                    )
                    await session.commit()
                    claim_status = "queued"
                except IntegrityError:
                    await session.rollback()
                    existing_run = await session.scalar(
                        select(AgentRun).where(
                            AgentRun.workspace_id == workspace_id,
                            AgentRun.idempotency_key == normalized_idempotency_key,
                        )
                    )
                    if existing_run is None:
                        raise
                    self._ensure_same_request(
                        existing_run,
                        job_id=job_id,
                        document_ids=normalized_document_ids,
                    )
                    run_id = existing_run.id
                    if existing_run.status == "queued":
                        self._ensure_executor_compatible(existing_run)
                        claim_status = "queued"
                    elif existing_run.status == "running" and self._lease_is_expired(
                        existing_run.lease_expires_at
                    ):
                        self._ensure_executor_compatible(existing_run)
                        claim_status = "running"
                        require_expired_lease = True

        execution_token: UUID | None = None
        if claim_status is not None:
            try:
                execution_token = await self._begin_execution(
                    run_id,
                    expected_status=claim_status,
                    event_kind=("running" if claim_status == "queued" else "resumed"),
                    require_expired_lease=require_expired_lease,
                )
            except RunAlreadyExecutingError:
                execution_token = None
        return RunDispatch(
            run_id=run_id,
            execution_token=execution_token,
        )

    async def execute_dispatch(self, dispatch: RunDispatch) -> None:
        """Execute only the exact lease claimed by ``prepare_run``/``prepare_resume``."""
        if dispatch.execution_token is None:
            return
        await self._execute(dispatch.run_id, dispatch.execution_token)

    async def get_run(
        self,
        *,
        workspace_id: str,
        run_id: UUID,
    ) -> AgentRun:
        async with self._session_factory() as session:
            run = await session.scalar(
                select(AgentRun).where(
                    AgentRun.id == run_id,
                    AgentRun.workspace_id == workspace_id,
                )
            )
        if run is None:
            raise RunResourceNotFoundError("Agent run was not found")
        return run

    async def resume_run(
        self,
        *,
        workspace_id: str,
        run_id: UUID,
    ) -> UUID:
        dispatch = await self.prepare_resume(
            workspace_id=workspace_id,
            run_id=run_id,
        )
        await self.execute_dispatch(dispatch)
        return dispatch.run_id

    async def prepare_resume(
        self,
        *,
        workspace_id: str,
        run_id: UUID,
    ) -> RunDispatch:
        """Claim a retryable run for background execution without executing it."""
        run = await self.get_run(workspace_id=workspace_id, run_id=run_id)
        stale_running = run.status == "running" and self._lease_is_expired(
            run.lease_expires_at
        )
        retryable_failure = run.status == "failed" and run.retryable
        if not retryable_failure and not stale_running:
            raise RunNotResumableError("Agent run cannot be resumed")
        self._ensure_executor_compatible(run)

        execution_token = await self._begin_execution(
            run_id,
            expected_status="failed" if retryable_failure else "running",
            event_kind="resumed",
            require_retryable=retryable_failure,
            require_expired_lease=stale_running,
        )
        return RunDispatch(
            run_id=run_id,
            execution_token=execution_token,
        )

    @staticmethod
    def _ensure_same_request(
        run: AgentRun,
        *,
        job_id: UUID,
        document_ids: list[str],
    ) -> None:
        if run.job_id != job_id or run.document_ids != document_ids:
            raise RunConflictError(
                "Idempotency key was already used with a different request"
            )

    def _executor_identity(self, attribute: str, fallback: str) -> str:
        value = getattr(self._executor, attribute, fallback)
        return value if isinstance(value, str) and value.strip() else fallback

    def _ensure_executor_compatible(self, run: AgentRun) -> None:
        if run.provider != self._executor_identity(
            "provider_name", "mock"
        ) or run.model != self._executor_identity(
            "model_name", "deterministic-mock-v1"
        ):
            raise RunExecutorMismatchError(
                "Configured executor does not match the persisted run"
            )

    @staticmethod
    def _lease_is_expired(expires_at: datetime | None) -> bool:
        if expires_at is None:
            return False
        now = datetime.now(UTC)
        comparable_now = (
            now if expires_at.tzinfo is not None else now.replace(tzinfo=None)
        )
        return expires_at <= comparable_now
