from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import Base, build_engine, build_session_factory
from app.models.agent_run import AgentRun
from app.models.job import Job


@pytest.mark.asyncio
async def test_agent_run_accepts_supported_statuses() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

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

        expected_statuses = {
            "queued",
            "running",
            "succeeded",
            "validation_failed",
            "failed",
        }
        runs = []
        for status in expected_statuses:
            run = AgentRun(
                workspace_id="workspace-1",
                job_id=job_id,
                idempotency_key=f"status-{status}-0001",
                document_ids=[str(uuid4())],
                status=status,
            )
            if status == "running":
                run.lease_expires_at = datetime.now(UTC)
                run.execution_token = uuid4()
            runs.append(run)

        async with test_session_factory() as session:
            session.add_all(runs)
            await session.commit()

        async with test_session_factory() as session:
            saved_statuses = set((await session.scalars(select(AgentRun.status))).all())

        assert saved_statuses == expected_statuses
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_agent_run_rejects_unknown_status() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

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

        invalid_run = AgentRun(
            workspace_id="workspace-1",
            job_id=job_id,
            idempotency_key="invalid-status-0001",
            document_ids=[str(uuid4())],
            status="paused",
        )

        async with test_session_factory() as session:
            session.add(invalid_run)

            with pytest.raises(IntegrityError) as exc_info:
                await session.commit()

            assert "ck_agent_runs_status_valid" in str(exc_info.value.orig)
            await session.rollback()
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_agent_run_persists_recovery_metadata() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        now = datetime.now(UTC)
        job = Job(
            workspace_id="workspace-1",
            title="Python Backend Engineer",
            description="Build FastAPI services.",
        )
        async with test_session_factory() as session:
            session.add(job)
            await session.flush()
            run = AgentRun(
                workspace_id="workspace-1",
                job_id=job.id,
                idempotency_key="recovery-metadata-0001",
                document_ids=[str(uuid4())],
                status="failed",
                provider="openai",
                model="test-model",
                current_node="draft",
                state_json={"requirements": [{"id": "req-1"}]},
                revision_count=1,
                attempt_count=2,
                retryable=True,
                error_code="connection_error",
                started_at=now,
                finished_at=now,
            )
            session.add(run)
            await session.commit()
            run_id = run.id

        async with test_session_factory() as session:
            saved = await session.get(AgentRun, run_id)

        assert saved is not None
        assert saved.provider == "openai"
        assert saved.model == "test-model"
        assert saved.current_node == "draft"
        assert saved.state_json == {"requirements": [{"id": "req-1"}]}
        assert saved.revision_count == 1
        assert saved.attempt_count == 2
        assert saved.retryable is True
        assert saved.error_code == "connection_error"
        assert saved.started_at is not None
        assert saved.finished_at is not None
    finally:
        await test_engine.dispose()


@pytest.mark.parametrize(
    ("lease_expires_at", "execution_token"),
    [
        (None, None),
        (datetime.now(UTC), None),
        (None, uuid4()),
    ],
)
@pytest.mark.asyncio
async def test_running_agent_run_requires_a_complete_execution_lease(
    lease_expires_at: datetime | None,
    execution_token: UUID | None,
) -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

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
            await session.flush()
            session.add(
                AgentRun(
                    workspace_id="workspace-1",
                    job_id=job.id,
                    idempotency_key=f"incomplete-lease-{uuid4()}",
                    document_ids=[str(uuid4())],
                    status="running",
                    lease_expires_at=lease_expires_at,
                    execution_token=execution_token,
                )
            )
            with pytest.raises(IntegrityError) as exc_info:
                await session.commit()
            assert "ck_agent_runs_execution_lease_consistent" in str(
                exc_info.value.orig
            )
    finally:
        await test_engine.dispose()


@pytest.mark.parametrize("field", ["revision_count", "attempt_count"])
@pytest.mark.asyncio
async def test_agent_run_rejects_negative_recovery_counters(field: str) -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

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
            await session.flush()
            run_data = {
                "workspace_id": "workspace-1",
                "job_id": job.id,
                "idempotency_key": f"negative-{field}-0001",
                "document_ids": [str(uuid4())],
                field: -1,
            }
            session.add(AgentRun(**run_data))
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_agent_run_database_rejects_job_from_another_workspace() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

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
            await session.flush()
            session.add(
                AgentRun(
                    workspace_id="workspace-2",
                    job_id=job.id,
                    idempotency_key="cross-workspace-job-0001",
                    document_ids=[str(uuid4())],
                )
            )

            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await test_engine.dispose()
