import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import Base, build_engine, build_session_factory
from app.models.job import Job


@pytest.mark.asyncio
async def test_job_can_round_trip_across_sessions() -> None:
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

        async with test_session_factory() as session:
            result = await session.execute(
                select(Job).where(
                    Job.id == job_id,
                    Job.workspace_id == "workspace-1",
                )
            )
            saved_job = result.scalar_one()

        assert saved_job.title == "Python Backend Engineer"
        assert saved_job.description == "Build FastAPI services."
        assert saved_job.created_at is not None
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_job_rejects_blank_description() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        invalid_job = Job(
            workspace_id="workspace-1",
            title="Python Backend Engineer",
            description="   ",
        )

        async with test_session_factory() as session:
            session.add(invalid_job)

            with pytest.raises(IntegrityError):
                await session.commit()

            await session.rollback()
    finally:
        await test_engine.dispose()
