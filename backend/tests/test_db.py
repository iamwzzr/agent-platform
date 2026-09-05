import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db import build_engine, build_session_factory, create_tables
from app.models.agent_run import AgentRun
from app.models.job import Job


@pytest.mark.asyncio
async def test_session_can_execute_query() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_session_factory() as session:
            result = await session.execute(text("SELECT 1"))

            assert result.scalar_one() == 1
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_create_tables_creates_domain_tables() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")

    try:
        await create_tables(test_engine)

        async with test_engine.connect() as connection:
            table_names = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )

        assert "jobs" in table_names
        assert "documents" in table_names
        assert "document_chunks" in table_names
        assert "agent_runs" in table_names
        assert "artifact_records" in table_names
        assert "run_events" in table_names
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_create_tables_upgrades_legacy_jobs_for_run_workspace_fk(
    tmp_path,
) -> None:
    database_path = tmp_path / "legacy-jobs.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    CREATE TABLE jobs (
                        id CHAR(32) NOT NULL PRIMARY KEY,
                        workspace_id VARCHAR(100) NOT NULL,
                        title VARCHAR(200) NOT NULL,
                        description TEXT NOT NULL,
                        created_at DATETIME NOT NULL
                    )
                    """
                )
            )

        await create_tables(test_engine)

        job = Job(
            workspace_id="workspace-1",
            title="Python Backend Engineer",
            description="Build FastAPI services.",
        )
        async with test_session_factory() as session:
            session.add(job)
            await session.commit()

        async with test_session_factory() as session:
            session.add(
                AgentRun(
                    workspace_id="workspace-1",
                    job_id=job.id,
                    idempotency_key="legacy-compatible-0001",
                    document_ids=[],
                )
            )
            await session.commit()

        async with test_session_factory() as session:
            session.add(
                AgentRun(
                    workspace_id="workspace-2",
                    job_id=job.id,
                    idempotency_key="legacy-cross-workspace-0001",
                    document_ids=[],
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await test_engine.dispose()
