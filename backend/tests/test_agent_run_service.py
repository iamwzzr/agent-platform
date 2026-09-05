import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import ANY, AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import Base, build_engine, build_session_factory
from app.models.agent_run import AgentRun
from app.models.artifact_record import ArtifactRecord
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.job import Job
from app.models.run_event import RunEvent
from app.run_execution import (
    InvalidRunExecutionResultError,
    RunExecutionLeaseLostError,
    RunExecutionResult,
)
from app.run_service import (
    AgentRunService,
    InvalidRunRequestError,
    RunConflictError,
    RunDocumentNotIngestedError,
    RunExecutorMismatchError,
    RunNotResumableError,
    RunResourceNotFoundError,
)
from app.schemas.artifact import (
    ApplicationArtifact,
    ArtifactValidation,
    Gap,
    Requirement,
)


def _successful_execution_result(
    run_id: UUID,
    workspace_id: str = "workspace-1",
) -> RunExecutionResult:
    requirement = Requirement(
        id="req-1",
        text="Five years of Kubernetes experience.",
        priority="high",
    )
    return RunExecutionResult(
        run_id=run_id,
        workspace_id=workspace_id,
        terminal_status="succeeded",
        artifact=ApplicationArtifact(
            run_id=run_id,
            requirements=[requirement],
            gaps=[
                Gap(
                    requirement_id=requirement.id,
                    reason_code="no_grounded_evidence",
                )
            ],
        ),
        validation=ArtifactValidation(passed=True),
        trusted_requirements=(requirement,),
        retrieved_evidence=(),
    )


async def _successful_executor(run_id: UUID, _: UUID) -> RunExecutionResult:
    return _successful_execution_result(run_id)


async def _load_run_state(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
) -> tuple[str | None, list[tuple[int, str]]]:
    async with session_factory() as session:
        status = await session.scalar(
            select(AgentRun.status).where(AgentRun.id == run_id)
        )
        events = list(
            (
                await session.scalars(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id)
                    .order_by(RunEvent.sequence)
                )
            ).all()
        )

    return status, [(event.sequence, event.kind) for event in events]


async def _load_terminal_event_data(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
) -> dict[str, object]:
    async with session_factory() as session:
        event_data = await session.scalar(
            select(RunEvent.data).where(
                RunEvent.run_id == run_id,
                RunEvent.sequence == 2,
            )
        )

    assert event_data is not None
    return event_data


async def _load_artifact_records(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
) -> list[ArtifactRecord]:
    async with session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(ArtifactRecord).where(ArtifactRecord.run_id == run_id)
                )
            ).all()
        )


async def _seed_run_input(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID]:
    job = Job(
        workspace_id="workspace-1",
        title="Python Backend Engineer",
        description="Build FastAPI services.",
    )
    document = Document(
        workspace_id="workspace-1",
        name="resume.txt",
        content="Built Python FastAPI services.",
    )
    async with session_factory() as session:
        session.add_all([job, document])
        await session.flush()
        session.add(
            DocumentChunk(
                workspace_id="workspace-1",
                document_id=document.id,
                position=0,
                content=document.content,
            )
        )
        await session.commit()
        return job.id, document.id


@pytest.mark.asyncio
async def test_start_run_rejects_empty_document_ids_before_persistence(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "agent-run-empty-documents.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    executor = AsyncMock()
    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        job = Job(
            workspace_id="workspace-1",
            title="Python Backend Engineer",
            description="Build FastAPI services.",
        )
        async with test_session_factory() as session:
            session.add(job)
            await session.commit()
            job_id = job.id

        with pytest.raises(
            InvalidRunRequestError,
            match="At least one document is required",
        ):
            await service.start_run(
                workspace_id="workspace-1",
                job_id=job_id,
                document_ids=[],
                idempotency_key="empty-documents-0001",
            )

        async with test_session_factory() as session:
            result = await session.execute(select(AgentRun))
            saved_runs = list(result.scalars().all())

        assert saved_runs == []
        executor.assert_not_awaited()
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_start_run_rejects_partially_uningested_document_scope(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "agent-run-uningested-document.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    executor = AsyncMock()
    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        job = Job(
            workspace_id="workspace-1",
            title="Python Backend Engineer",
            description="Build FastAPI services.",
        )
        ingested_document = Document(
            workspace_id="workspace-1",
            name="resume.txt",
            content="Built Python FastAPI services.",
        )
        uningested_document = Document(
            workspace_id="workspace-1",
            name="portfolio.txt",
            content="Built React applications.",
        )
        async with test_session_factory() as session:
            session.add_all([job, ingested_document, uningested_document])
            await session.flush()
            session.add(
                DocumentChunk(
                    workspace_id="workspace-1",
                    document_id=ingested_document.id,
                    position=0,
                    content=ingested_document.content,
                )
            )
            await session.commit()
            job_id = job.id
            ingested_document_id = ingested_document.id
            uningested_document_id = uningested_document.id

        with pytest.raises(
            RunDocumentNotIngestedError,
            match="Run documents have not been ingested",
        ):
            await service.start_run(
                workspace_id="workspace-1",
                job_id=job_id,
                document_ids=[ingested_document_id, uningested_document_id],
                idempotency_key="partially-uningested-documents-0001",
            )

        async with test_session_factory() as session:
            result = await session.execute(select(AgentRun))
            saved_runs = list(result.scalars().all())

        assert saved_runs == []
        executor.assert_not_awaited()
    finally:
        await test_engine.dispose()


@pytest.mark.parametrize(
    ("input_kind", "visibility"),
    [
        ("job", "missing"),
        ("job", "other_workspace"),
        ("document", "missing"),
        ("document", "other_workspace"),
    ],
)
@pytest.mark.asyncio
async def test_start_run_rejects_input_not_visible_to_workspace(
    tmp_path: Path,
    input_kind: str,
    visibility: str,
) -> None:
    database_path = tmp_path / f"agent-run-{input_kind}-{visibility}.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    executor = AsyncMock()
    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        job_id = uuid4()
        document_id = uuid4()
        records = []

        if not (input_kind == "job" and visibility == "missing"):
            job_workspace_id = (
                "workspace-2"
                if input_kind == "job" and visibility == "other_workspace"
                else "workspace-1"
            )
            records.append(
                Job(
                    id=job_id,
                    workspace_id=job_workspace_id,
                    title="Python Backend Engineer",
                    description="Build FastAPI services.",
                )
            )

        if not (input_kind == "document" and visibility == "missing"):
            document_workspace_id = (
                "workspace-2"
                if input_kind == "document" and visibility == "other_workspace"
                else "workspace-1"
            )
            records.extend(
                [
                    Document(
                        id=document_id,
                        workspace_id=document_workspace_id,
                        name="resume.txt",
                        content="Built Python FastAPI services.",
                    ),
                    DocumentChunk(
                        workspace_id=document_workspace_id,
                        document_id=document_id,
                        position=0,
                        content="Built Python FastAPI services.",
                    ),
                ]
            )

        async with test_session_factory() as session:
            session.add_all(records)
            await session.commit()

        with pytest.raises(
            RunResourceNotFoundError,
            match="Run inputs were not found",
        ):
            await service.start_run(
                workspace_id="workspace-1",
                job_id=job_id,
                document_ids=[document_id],
                idempotency_key=f"{input_kind}-{visibility}-0001",
            )

        async with test_session_factory() as session:
            result = await session.execute(select(AgentRun))
            saved_runs = list(result.scalars().all())

        assert saved_runs == []
        executor.assert_not_awaited()
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_start_run_is_idempotent_for_equivalent_document_scope(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "agent-run-service.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    executor = AsyncMock(side_effect=_successful_executor)
    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        job = Job(
            workspace_id="workspace-1",
            title="Python Backend Engineer",
            description="Build FastAPI services.",
        )
        first_document = Document(
            workspace_id="workspace-1",
            name="resume.txt",
            content="Built Python FastAPI services.",
        )
        second_document = Document(
            workspace_id="workspace-1",
            name="portfolio.txt",
            content="Built React applications.",
        )
        async with test_session_factory() as session:
            session.add_all([job, first_document, second_document])
            await session.flush()
            session.add_all(
                [
                    DocumentChunk(
                        workspace_id="workspace-1",
                        document_id=first_document.id,
                        position=0,
                        content=first_document.content,
                    ),
                    DocumentChunk(
                        workspace_id="workspace-1",
                        document_id=second_document.id,
                        position=0,
                        content=second_document.content,
                    ),
                ]
            )
            await session.commit()
            job_id = job.id
            first_document_id = first_document.id
            second_document_id = second_document.id

        first_run_id = await service.start_run(
            workspace_id="workspace-1",
            job_id=job_id,
            document_ids=[second_document_id, first_document_id, first_document_id],
            idempotency_key="same-request-0001",
        )
        second_run_id = await service.start_run(
            workspace_id="workspace-1",
            job_id=job_id,
            document_ids=[first_document_id, second_document_id],
            idempotency_key="same-request-0001",
        )

        async with test_session_factory() as session:
            result = await session.execute(select(AgentRun))
            saved_runs = list(result.scalars().all())
        saved_state = await _load_run_state(test_session_factory, first_run_id)
        saved_artifacts = await _load_artifact_records(
            test_session_factory,
            first_run_id,
        )

        assert second_run_id == first_run_id
        assert len(saved_runs) == 1
        assert saved_runs[0].id == first_run_id
        assert saved_runs[0].document_ids == sorted(
            [str(first_document_id), str(second_document_id)]
        )
        assert saved_state == (
            "succeeded",
            [(0, "queued"), (1, "running"), (2, "succeeded")],
        )
        assert len(saved_artifacts) == 1
        executor.assert_awaited_once_with(first_run_id, ANY)
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_idempotent_replay_claims_a_queued_run_left_before_dispatch(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "agent-run-queued-replay.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    executor = AsyncMock(side_effect=_successful_executor)
    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        job_id, document_id = await _seed_run_input(test_session_factory)
        queued_run = AgentRun(
            workspace_id="workspace-1",
            job_id=job_id,
            idempotency_key="queued-replay-0001",
            document_ids=[str(document_id)],
        )
        async with test_session_factory() as session:
            session.add(queued_run)
            await session.flush()
            session.add(RunEvent(run_id=queued_run.id, sequence=0, kind="queued"))
            await session.commit()
        run_id = queued_run.id

        replayed_run_id = await service.start_run(
            workspace_id="workspace-1",
            job_id=job_id,
            document_ids=[document_id],
            idempotency_key="queued-replay-0001",
        )

        assert replayed_run_id == run_id
        assert await _load_run_state(test_session_factory, run_id) == (
            "succeeded",
            [(0, "queued"), (1, "running"), (2, "succeeded")],
        )
        executor.assert_awaited_once_with(run_id, ANY)
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_idempotent_replay_does_not_duplicate_running_execution(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "agent-run-concurrent-replay.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    execution_started = asyncio.Event()
    release_execution = asyncio.Event()
    execution_calls = 0

    async def executor(run_id: UUID, _: UUID) -> RunExecutionResult:
        nonlocal execution_calls
        execution_calls += 1
        execution_started.set()
        await release_execution.wait()
        return _successful_execution_result(run_id)

    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        job_id, document_id = await _seed_run_input(test_session_factory)
        first_request = asyncio.create_task(
            service.start_run(
                workspace_id="workspace-1",
                job_id=job_id,
                document_ids=[document_id],
                idempotency_key="concurrent-replay-0001",
            )
        )
        await execution_started.wait()

        replayed_run_id = await service.start_run(
            workspace_id="workspace-1",
            job_id=job_id,
            document_ids=[document_id],
            idempotency_key="concurrent-replay-0001",
        )
        release_execution.set()
        first_run_id = await first_request

        assert replayed_run_id == first_run_id
        assert execution_calls == 1
        assert await _load_run_state(test_session_factory, first_run_id) == (
            "succeeded",
            [(0, "queued"), (1, "running"), (2, "succeeded")],
        )
    finally:
        release_execution.set()
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_cancelled_execution_is_recorded_as_retryable_failure(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "agent-run-cancelled.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    execution_started = asyncio.Event()
    never_finish = asyncio.Event()

    async def executor(_: UUID, __: UUID) -> RunExecutionResult:
        execution_started.set()
        await never_finish.wait()
        raise AssertionError("unreachable")

    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        job_id, document_id = await _seed_run_input(test_session_factory)
        request = asyncio.create_task(
            service.start_run(
                workspace_id="workspace-1",
                job_id=job_id,
                document_ids=[document_id],
                idempotency_key="cancelled-run-0001",
            )
        )
        await execution_started.wait()
        request.cancel()

        with pytest.raises(asyncio.CancelledError):
            await request

        async with test_session_factory() as session:
            run = await session.scalar(
                select(AgentRun).where(AgentRun.idempotency_key == "cancelled-run-0001")
            )
        assert run is not None
        assert run.status == "failed"
        assert run.retryable is True
        assert run.error_code == "execution_interrupted"
        assert run.lease_expires_at is None
        assert await _load_terminal_event_data(test_session_factory, run.id) == {
            "reason_code": "execution_interrupted",
            "retryable": True,
        }
    finally:
        never_finish.set()
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_resume_reclaims_only_an_expired_running_lease(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "agent-run-expired-lease.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    executor = AsyncMock(side_effect=_successful_executor)
    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        job_id, document_id = await _seed_run_input(test_session_factory)
        expired_run = AgentRun(
            workspace_id="workspace-1",
            job_id=job_id,
            idempotency_key="expired-lease-0001",
            document_ids=[str(document_id)],
            status="running",
            attempt_count=1,
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
            execution_token=uuid4(),
        )
        active_run = AgentRun(
            workspace_id="workspace-1",
            job_id=job_id,
            idempotency_key="active-lease-0001",
            document_ids=[str(document_id)],
            status="running",
            attempt_count=1,
            lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            execution_token=uuid4(),
        )
        async with test_session_factory() as session:
            session.add_all([expired_run, active_run])
            await session.flush()
            session.add_all(
                [
                    RunEvent(run_id=expired_run.id, sequence=0, kind="queued"),
                    RunEvent(run_id=expired_run.id, sequence=1, kind="running"),
                    RunEvent(run_id=active_run.id, sequence=0, kind="queued"),
                    RunEvent(run_id=active_run.id, sequence=1, kind="running"),
                ]
            )
            await session.commit()

        resumed_id = await service.resume_run(
            workspace_id="workspace-1",
            run_id=expired_run.id,
        )
        with pytest.raises(RunNotResumableError):
            await service.resume_run(
                workspace_id="workspace-1",
                run_id=active_run.id,
            )

        assert resumed_id == expired_run.id
        assert await _load_run_state(test_session_factory, resumed_id) == (
            "succeeded",
            [
                (0, "queued"),
                (1, "running"),
                (2, "resumed"),
                (3, "succeeded"),
            ],
        )
        executor.assert_awaited_once_with(expired_run.id, ANY)
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_resume_preserves_failure_when_executor_identity_does_not_match(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "agent-run-executor-mismatch.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    executor = AsyncMock(side_effect=_successful_executor)
    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        job_id, document_id = await _seed_run_input(test_session_factory)
        run = AgentRun(
            workspace_id="workspace-1",
            job_id=job_id,
            idempotency_key="executor-mismatch-0001",
            document_ids=[str(document_id)],
            status="failed",
            provider="openai",
            model="gpt-test",
            attempt_count=1,
            retryable=True,
            error_code="connection_error",
        )
        async with test_session_factory() as session:
            session.add(run)
            await session.flush()
            session.add_all(
                [
                    RunEvent(run_id=run.id, sequence=0, kind="queued"),
                    RunEvent(run_id=run.id, sequence=1, kind="running"),
                    RunEvent(
                        run_id=run.id,
                        sequence=2,
                        kind="failed",
                        data={
                            "reason_code": "connection_error",
                            "retryable": True,
                        },
                    ),
                ]
            )
            await session.commit()
            run_id = run.id

        with pytest.raises(RunExecutorMismatchError):
            await service.resume_run(
                workspace_id="workspace-1",
                run_id=run_id,
            )

        async with test_session_factory() as session:
            preserved = await session.get(AgentRun, run_id)
        assert preserved is not None
        assert preserved.status == "failed"
        assert preserved.retryable is True
        assert preserved.error_code == "connection_error"
        assert preserved.attempt_count == 1
        assert await _load_run_state(test_session_factory, run_id) == (
            "failed",
            [(0, "queued"), (1, "running"), (2, "failed")],
        )
        executor.assert_not_awaited()
    finally:
        await test_engine.dispose()


@pytest.mark.parametrize("status", ["queued", "running"])
@pytest.mark.asyncio
async def test_start_preserves_pending_run_when_executor_identity_does_not_match(
    tmp_path: Path,
    status: str,
) -> None:
    database_path = tmp_path / f"agent-run-{status}-executor-mismatch.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    executor = AsyncMock(side_effect=_successful_executor)
    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        job_id, document_id = await _seed_run_input(test_session_factory)
        execution_token = uuid4() if status == "running" else None
        lease_expires_at = (
            datetime.now(UTC) - timedelta(seconds=1) if status == "running" else None
        )
        run = AgentRun(
            workspace_id="workspace-1",
            job_id=job_id,
            idempotency_key=f"{status}-executor-mismatch-0001",
            document_ids=[str(document_id)],
            status=status,
            provider="openai",
            model="private-model-marker",
            attempt_count=1 if status == "running" else 0,
            lease_expires_at=lease_expires_at,
            execution_token=execution_token,
        )
        async with test_session_factory() as session:
            session.add(run)
            await session.flush()
            session.add(RunEvent(run_id=run.id, sequence=0, kind="queued"))
            if status == "running":
                session.add(RunEvent(run_id=run.id, sequence=1, kind="running"))
            await session.commit()
            run_id = run.id

        with pytest.raises(RunExecutorMismatchError):
            await service.start_run(
                workspace_id="workspace-1",
                job_id=job_id,
                document_ids=[document_id],
                idempotency_key=f"{status}-executor-mismatch-0001",
            )

        async with test_session_factory() as session:
            preserved = await session.get(AgentRun, run_id)
        assert preserved is not None
        assert preserved.status == status
        assert preserved.provider == "openai"
        assert preserved.model == "private-model-marker"
        assert preserved.attempt_count == (1 if status == "running" else 0)
        assert preserved.execution_token == execution_token
        executor.assert_not_awaited()
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_heartbeat_keeps_a_long_running_execution_lease_active(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "agent-run-heartbeat.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    execution_started = asyncio.Event()
    release_execution = asyncio.Event()
    execution_calls = 0

    async def executor(run_id: UUID, _: UUID) -> RunExecutionResult:
        nonlocal execution_calls
        execution_calls += 1
        execution_started.set()
        await release_execution.wait()
        return _successful_execution_result(run_id)

    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
        execution_lease_seconds=1,
    )
    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        job_id, document_id = await _seed_run_input(test_session_factory)
        request = asyncio.create_task(
            service.start_run(
                workspace_id="workspace-1",
                job_id=job_id,
                document_ids=[document_id],
                idempotency_key="heartbeat-run-0001",
            )
        )
        await execution_started.wait()

        async with test_session_factory() as session:
            run = await session.scalar(
                select(AgentRun).where(AgentRun.idempotency_key == "heartbeat-run-0001")
            )
        assert run is not None
        initial_expiry = run.lease_expires_at
        assert initial_expiry is not None

        await asyncio.sleep(1.05)

        async with test_session_factory() as session:
            refreshed_run = await session.get(AgentRun, run.id)
        assert refreshed_run is not None
        assert refreshed_run.lease_expires_at is not None
        assert refreshed_run.lease_expires_at > initial_expiry
        with pytest.raises(RunNotResumableError):
            await service.resume_run(
                workspace_id="workspace-1",
                run_id=run.id,
            )

        release_execution.set()
        assert await request == run.id
        assert execution_calls == 1
    finally:
        release_execution.set()
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_heartbeat_does_not_report_lease_loss_after_terminal_commit(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "agent-run-terminal-heartbeat-race.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    terminal_committed = asyncio.Event()
    release_completion = asyncio.Event()

    class PausingCompletionService(AgentRunService):
        async def _complete_success(
            self,
            run_id: UUID,
            *,
            execution_token: UUID,
            artifact: ApplicationArtifact,
            validation: ArtifactValidation,
        ) -> None:
            await super()._complete_success(
                run_id,
                execution_token=execution_token,
                artifact=artifact,
                validation=validation,
            )
            terminal_committed.set()
            await release_completion.wait()

    service = PausingCompletionService(
        session_factory=test_session_factory,
        executor=_successful_executor,
        execution_lease_seconds=1,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        job_id, document_id = await _seed_run_input(test_session_factory)
        request = asyncio.create_task(
            service.start_run(
                workspace_id="workspace-1",
                job_id=job_id,
                document_ids=[document_id],
                idempotency_key="terminal-heartbeat-race-0001",
            )
        )
        await terminal_committed.wait()
        await asyncio.sleep(0.45)

        release_completion.set()
        run_id = await request

        assert await _load_run_state(test_session_factory, run_id) == (
            "succeeded",
            [(0, "queued"), (1, "running"), (2, "succeeded")],
        )
        assert len(await _load_artifact_records(test_session_factory, run_id)) == 1
    finally:
        release_completion.set()
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_worker_that_loses_execution_token_cannot_publish_artifact(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "agent-run-fenced-worker.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    execution_started = asyncio.Event()
    release_execution = asyncio.Event()

    async def executor(run_id: UUID, _: UUID) -> RunExecutionResult:
        execution_started.set()
        await release_execution.wait()
        return _successful_execution_result(run_id)

    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        job_id, document_id = await _seed_run_input(test_session_factory)
        request = asyncio.create_task(
            service.start_run(
                workspace_id="workspace-1",
                job_id=job_id,
                document_ids=[document_id],
                idempotency_key="fenced-worker-0001",
            )
        )
        await execution_started.wait()

        replacement_token = uuid4()
        async with test_session_factory() as session:
            run = await session.scalar(
                select(AgentRun).where(AgentRun.idempotency_key == "fenced-worker-0001")
            )
            assert run is not None
            run_id = run.id
            run.execution_token = replacement_token
            await session.commit()

        release_execution.set()
        with pytest.raises(RunExecutionLeaseLostError):
            await request

        async with test_session_factory() as session:
            fenced_run = await session.get(AgentRun, run_id)
        assert fenced_run is not None
        assert fenced_run.status == "running"
        assert fenced_run.execution_token == replacement_token
        assert await _load_artifact_records(test_session_factory, run_id) == []
        assert await _load_run_state(test_session_factory, run_id) == (
            "running",
            [(0, "queued"), (1, "running")],
        )
    finally:
        release_execution.set()
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_heartbeat_cancels_old_worker_after_new_owner_finishes(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "agent-run-old-worker-cancelled.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    execution_started = asyncio.Event()
    execution_cancelled = asyncio.Event()

    async def executor(_: UUID, __: UUID) -> RunExecutionResult:
        execution_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            execution_cancelled.set()
            raise
        raise AssertionError("unreachable")

    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
        execution_lease_seconds=1,
    )
    request: asyncio.Task[UUID] | None = None

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        job_id, document_id = await _seed_run_input(test_session_factory)
        request = asyncio.create_task(
            service.start_run(
                workspace_id="workspace-1",
                job_id=job_id,
                document_ids=[document_id],
                idempotency_key="old-worker-cancelled-0001",
            )
        )
        await execution_started.wait()

        async with test_session_factory() as session:
            run = await session.scalar(
                select(AgentRun).where(
                    AgentRun.idempotency_key == "old-worker-cancelled-0001"
                )
            )
            assert run is not None
            run_id = run.id
            run.status = "failed"
            run.retryable = False
            run.error_code = "replacement_worker_finished"
            run.finished_at = datetime.now(UTC)
            run.lease_expires_at = None
            run.execution_token = None
            await session.commit()

        await asyncio.wait_for(execution_cancelled.wait(), timeout=1.5)
        with pytest.raises(RunExecutionLeaseLostError):
            await request
        assert await _load_artifact_records(test_session_factory, run_id) == []
    finally:
        if request is not None:
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_database_execution_failure_is_recorded_as_retryable(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "agent-run-database-failure.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    expected_error = SQLAlchemyError("private-database-error-marker")

    async def executor(_: UUID, __: UUID) -> RunExecutionResult:
        raise expected_error

    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        job_id, document_id = await _seed_run_input(test_session_factory)

        with pytest.raises(SQLAlchemyError) as exc_info:
            await service.start_run(
                workspace_id="workspace-1",
                job_id=job_id,
                document_ids=[document_id],
                idempotency_key="database-failure-0001",
            )

        assert exc_info.value is expected_error
        async with test_session_factory() as session:
            run = await session.scalar(
                select(AgentRun).where(
                    AgentRun.idempotency_key == "database-failure-0001"
                )
            )
        assert run is not None
        assert run.status == "failed"
        assert run.retryable is True
        assert run.error_code == "checkpoint_persistence_error"
        event_data = await _load_terminal_event_data(test_session_factory, run.id)
        assert event_data == {
            "reason_code": "checkpoint_persistence_error",
            "retryable": True,
        }
        assert "private-database-error-marker" not in repr(event_data)
    finally:
        await test_engine.dispose()


@pytest.mark.parametrize("conflicting_field", ["job_id", "document_ids"])
@pytest.mark.asyncio
async def test_start_run_rejects_reused_key_for_different_request(
    tmp_path: Path,
    conflicting_field: str,
) -> None:
    database_path = tmp_path / "agent-run-conflict.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    executor = AsyncMock(side_effect=_successful_executor)
    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        first_job = Job(
            workspace_id="workspace-1",
            title="Python Backend Engineer",
            description="Build FastAPI services.",
        )
        second_job = Job(
            workspace_id="workspace-1",
            title="Frontend Engineer",
            description="Build React applications.",
        )
        first_document = Document(
            workspace_id="workspace-1",
            name="resume.txt",
            content="Built Python FastAPI services.",
        )
        second_document = Document(
            workspace_id="workspace-1",
            name="portfolio.txt",
            content="Built React applications.",
        )
        async with test_session_factory() as session:
            session.add_all([first_job, second_job, first_document, second_document])
            await session.flush()
            session.add_all(
                [
                    DocumentChunk(
                        workspace_id="workspace-1",
                        document_id=first_document.id,
                        position=0,
                        content=first_document.content,
                    ),
                    DocumentChunk(
                        workspace_id="workspace-1",
                        document_id=second_document.id,
                        position=0,
                        content=second_document.content,
                    ),
                ]
            )
            await session.commit()
            first_job_id = first_job.id
            second_job_id = second_job.id
            first_document_id = first_document.id
            second_document_id = second_document.id

        first_run_id = await service.start_run(
            workspace_id="workspace-1",
            job_id=first_job_id,
            document_ids=[first_document_id],
            idempotency_key="reused-key-0001",
        )

        conflicting_job_id = (
            second_job_id if conflicting_field == "job_id" else first_job_id
        )
        conflicting_document_ids = (
            [second_document_id]
            if conflicting_field == "document_ids"
            else [first_document_id]
        )
        with pytest.raises(
            RunConflictError,
            match="Idempotency key was already used with a different request",
        ):
            await service.start_run(
                workspace_id="workspace-1",
                job_id=conflicting_job_id,
                document_ids=conflicting_document_ids,
                idempotency_key="reused-key-0001",
            )

        async with test_session_factory() as session:
            result = await session.execute(select(AgentRun))
            saved_runs = list(result.scalars().all())

        assert len(saved_runs) == 1
        assert saved_runs[0].id == first_run_id
        assert saved_runs[0].job_id == first_job_id
        assert saved_runs[0].document_ids == [str(first_document_id)]
        executor.assert_awaited_once_with(first_run_id, ANY)
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_start_run_marks_running_before_executor_and_succeeded_after_return(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "agent-run-success-lifecycle.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    observed_states: list[tuple[str | None, list[tuple[int, str]]]] = []

    async def executor(run_id: UUID, _: UUID) -> RunExecutionResult:
        observed_states.append(await _load_run_state(test_session_factory, run_id))
        return _successful_execution_result(run_id)

    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        job = Job(
            workspace_id="workspace-1",
            title="Python Backend Engineer",
            description="Build FastAPI services.",
        )
        document = Document(
            workspace_id="workspace-1",
            name="resume.txt",
            content="Built Python FastAPI services.",
        )
        async with test_session_factory() as session:
            session.add_all([job, document])
            await session.flush()
            session.add(
                DocumentChunk(
                    workspace_id="workspace-1",
                    document_id=document.id,
                    position=0,
                    content=document.content,
                )
            )
            await session.commit()
            job_id = job.id
            document_id = document.id

        run_id = await service.start_run(
            workspace_id="workspace-1",
            job_id=job_id,
            document_ids=[document_id],
            idempotency_key="success-lifecycle-0001",
        )

        saved_state = await _load_run_state(test_session_factory, run_id)
        saved_artifacts = await _load_artifact_records(test_session_factory, run_id)
        expected_result = _successful_execution_result(run_id)

        assert observed_states == [("running", [(0, "queued"), (1, "running")])]
        assert saved_state == (
            "succeeded",
            [(0, "queued"), (1, "running"), (2, "succeeded")],
        )
        assert len(saved_artifacts) == 1
        assert expected_result.artifact is not None
        assert ApplicationArtifact.model_validate(saved_artifacts[0].content) == (
            expected_result.artifact
        )
        assert ArtifactValidation.model_validate(saved_artifacts[0].validation) == (
            expected_result.validation
        )
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_start_run_marks_failed_and_reraises_when_executor_raises(
    tmp_path: Path,
) -> None:
    class ExpectedExecutorError(RuntimeError):
        pass

    database_path = tmp_path / "agent-run-failure-lifecycle.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    expected_error = ExpectedExecutorError("expected executor failure")
    observed_states: list[tuple[str | None, list[tuple[int, str]]]] = []

    async def executor(run_id: UUID, _: UUID) -> None:
        observed_states.append(await _load_run_state(test_session_factory, run_id))
        raise expected_error

    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        job = Job(
            workspace_id="workspace-1",
            title="Python Backend Engineer",
            description="Build FastAPI services.",
        )
        document = Document(
            workspace_id="workspace-1",
            name="resume.txt",
            content="Built Python FastAPI services.",
        )
        async with test_session_factory() as session:
            session.add_all([job, document])
            await session.flush()
            session.add(
                DocumentChunk(
                    workspace_id="workspace-1",
                    document_id=document.id,
                    position=0,
                    content=document.content,
                )
            )
            await session.commit()
            job_id = job.id
            document_id = document.id

        with pytest.raises(ExpectedExecutorError) as exc_info:
            await service.start_run(
                workspace_id="workspace-1",
                job_id=job_id,
                document_ids=[document_id],
                idempotency_key="failure-lifecycle-0001",
            )

        async with test_session_factory() as session:
            failed_run = await session.scalar(
                select(AgentRun).where(
                    AgentRun.workspace_id == "workspace-1",
                    AgentRun.idempotency_key == "failure-lifecycle-0001",
                )
            )

        assert exc_info.value is expected_error
        assert observed_states == [("running", [(0, "queued"), (1, "running")])]
        assert failed_run is not None
        assert await _load_run_state(test_session_factory, failed_run.id) == (
            "failed",
            [(0, "queued"), (1, "running"), (2, "failed")],
        )
        assert await _load_artifact_records(test_session_factory, failed_run.id) == []
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_start_run_records_controlled_validation_failure(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "agent-run-validation-failure.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    validation = ArtifactValidation(
        passed=False,
        uncovered_requirement_ids=["req-1"],
    )
    requirement = Requirement(
        id="req-1",
        text="Build FastAPI services.",
        priority="high",
    )

    async def executor(run_id: UUID, _: UUID) -> RunExecutionResult:
        return RunExecutionResult(
            run_id=run_id,
            workspace_id="workspace-1",
            terminal_status="validation_failed",
            artifact=None,
            validation=validation,
            trusted_requirements=(requirement,),
            retrieved_evidence=(),
        )

    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        job_id, document_id = await _seed_run_input(test_session_factory)

        run_id = await service.start_run(
            workspace_id="workspace-1",
            job_id=job_id,
            document_ids=[document_id],
            idempotency_key="validation-failure-0001",
        )

        assert await _load_run_state(test_session_factory, run_id) == (
            "validation_failed",
            [(0, "queued"), (1, "running"), (2, "validation_failed")],
        )
        assert await _load_terminal_event_data(test_session_factory, run_id) == {
            "reason_code": "validation_failed",
            "validation": validation.model_dump(mode="json"),
        }
        assert await _load_artifact_records(test_session_factory, run_id) == []
    finally:
        await test_engine.dispose()


@pytest.mark.parametrize(
    ("invalid_result_kind", "expected_message"),
    [
        ("missing", "Run executor returned an invalid result"),
        ("mismatched_run_id", "Run execution result does not match the run"),
        (
            "mismatched_workspace",
            "Run execution result does not match the workspace",
        ),
    ],
)
@pytest.mark.asyncio
async def test_start_run_marks_failed_for_invalid_executor_result(
    tmp_path: Path,
    invalid_result_kind: str,
    expected_message: str,
) -> None:
    database_path = tmp_path / f"agent-run-invalid-result-{invalid_result_kind}.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)

    async def executor(run_id: UUID, _: UUID) -> object:
        if invalid_result_kind == "missing":
            return None
        if invalid_result_kind == "mismatched_workspace":
            return _successful_execution_result(run_id, "workspace-2")
        mismatched_run_id = UUID(int=run_id.int ^ 1)
        return _successful_execution_result(mismatched_run_id)

    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,  # type: ignore[arg-type]
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        job_id, document_id = await _seed_run_input(test_session_factory)

        with pytest.raises(
            InvalidRunExecutionResultError,
            match=expected_message,
        ):
            await service.start_run(
                workspace_id="workspace-1",
                job_id=job_id,
                document_ids=[document_id],
                idempotency_key=f"invalid-result-{invalid_result_kind}-0001",
            )

        async with test_session_factory() as session:
            failed_run_id = await session.scalar(
                select(AgentRun.id).where(
                    AgentRun.workspace_id == "workspace-1",
                    AgentRun.idempotency_key
                    == f"invalid-result-{invalid_result_kind}-0001",
                )
            )

        assert failed_run_id is not None
        assert await _load_run_state(test_session_factory, failed_run_id) == (
            "failed",
            [(0, "queued"), (1, "running"), (2, "failed")],
        )
        assert await _load_terminal_event_data(
            test_session_factory,
            failed_run_id,
        ) == {
            "reason_code": "invalid_executor_result",
            "retryable": False,
        }
        assert await _load_artifact_records(test_session_factory, failed_run_id) == []
    finally:
        await test_engine.dispose()


@pytest.mark.parametrize("mutation", ["validation", "artifact"])
@pytest.mark.asyncio
async def test_start_run_revalidates_mutated_execution_result(
    tmp_path: Path,
    mutation: str,
) -> None:
    database_path = tmp_path / f"agent-run-mutated-result-{mutation}.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)

    async def executor(run_id: UUID, _: UUID) -> RunExecutionResult:
        result = _successful_execution_result(run_id)
        if mutation == "validation":
            result.validation.uncovered_requirement_ids.append("req-1")
        else:
            assert result.artifact is not None
            result.artifact.gaps.clear()
        return result

    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        job_id, document_id = await _seed_run_input(test_session_factory)

        with pytest.raises(InvalidRunExecutionResultError):
            await service.start_run(
                workspace_id="workspace-1",
                job_id=job_id,
                document_ids=[document_id],
                idempotency_key=f"mutated-result-{mutation}-0001",
            )

        async with test_session_factory() as session:
            run = await session.scalar(
                select(AgentRun).where(
                    AgentRun.idempotency_key == f"mutated-result-{mutation}-0001"
                )
            )
        assert run is not None
        assert run.status == "failed"
        assert run.retryable is False
        assert await _load_artifact_records(test_session_factory, run.id) == []
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_success_completion_is_atomic_when_artifact_insert_fails(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "agent-run-artifact-atomicity.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    service = AgentRunService(
        session_factory=test_session_factory,
        executor=_successful_executor,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.execute(
                text(
                    """
                    CREATE TRIGGER reject_artifact_record_insert
                    BEFORE INSERT ON artifact_records
                    BEGIN
                        SELECT RAISE(ABORT, 'forced artifact insert failure');
                    END
                    """
                )
            )

        job_id, document_id = await _seed_run_input(test_session_factory)

        with pytest.raises(IntegrityError, match="forced artifact insert failure"):
            await service.start_run(
                workspace_id="workspace-1",
                job_id=job_id,
                document_ids=[document_id],
                idempotency_key="artifact-atomicity-0001",
            )

        async with test_session_factory() as session:
            run_id = await session.scalar(
                select(AgentRun.id).where(
                    AgentRun.workspace_id == "workspace-1",
                    AgentRun.idempotency_key == "artifact-atomicity-0001",
                )
            )

        assert run_id is not None
        status, events = await _load_run_state(test_session_factory, run_id)
        assert status != "succeeded"
        assert (2, "succeeded") not in events
        assert await _load_artifact_records(test_session_factory, run_id) == []
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_validation_failure_transition_error_becomes_retryable_failure(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "agent-run-validation-transition.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    validation = ArtifactValidation(
        passed=False,
        uncovered_requirement_ids=["req-1"],
    )
    requirement = Requirement(
        id="req-1",
        text="Build FastAPI services.",
        priority="high",
    )

    async def executor(run_id: UUID, _: UUID) -> RunExecutionResult:
        return RunExecutionResult(
            run_id=run_id,
            workspace_id="workspace-1",
            terminal_status="validation_failed",
            artifact=None,
            validation=validation,
            trusted_requirements=(requirement,),
            retrieved_evidence=(),
        )

    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
    )

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.execute(
                text(
                    """
                    CREATE TRIGGER reject_validation_failure_transition
                    BEFORE UPDATE OF status ON agent_runs
                    WHEN NEW.status = 'validation_failed'
                    BEGIN
                        SELECT RAISE(ABORT, 'forced validation transition failure');
                    END
                    """
                )
            )
        job_id, document_id = await _seed_run_input(test_session_factory)

        with pytest.raises(
            IntegrityError,
            match="forced validation transition failure",
        ):
            await service.start_run(
                workspace_id="workspace-1",
                job_id=job_id,
                document_ids=[document_id],
                idempotency_key="validation-transition-0001",
            )

        async with test_session_factory() as session:
            run = await session.scalar(
                select(AgentRun).where(
                    AgentRun.idempotency_key == "validation-transition-0001"
                )
            )
        assert run is not None
        assert run.status == "failed"
        assert run.retryable is True
        assert run.error_code == "persistence_error"
        assert await _load_run_state(test_session_factory, run.id) == (
            "failed",
            [(0, "queued"), (1, "running"), (2, "failed")],
        )
        assert await _load_artifact_records(test_session_factory, run.id) == []
    finally:
        await test_engine.dispose()
