from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import Base, build_engine, build_session_factory
from app.models.agent_run import AgentRun
from app.models.artifact_record import ArtifactRecord
from app.models.job import Job
from app.schemas.artifact import (
    ApplicationArtifact,
    ArtifactValidation,
    Gap,
    Requirement,
)


async def _create_run(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    idempotency_key: str,
) -> UUID:
    job = Job(
        workspace_id="workspace-1",
        title="Python Backend Engineer",
        description="Build FastAPI services.",
    )
    async with session_factory() as session:
        session.add(job)
        await session.flush()
        run = AgentRun(
            workspace_id="workspace-1",
            job_id=job.id,
            idempotency_key=idempotency_key,
            document_ids=[str(uuid4())],
            status="succeeded",
        )
        session.add(run)
        await session.commit()
        return run.id


def _artifact_payload(run_id: UUID) -> dict[str, object]:
    requirement = Requirement(
        id="req-1",
        text="Five years of Kubernetes experience.",
        priority="high",
    )
    artifact = ApplicationArtifact(
        run_id=run_id,
        requirements=[requirement],
        gaps=[
            Gap(
                requirement_id=requirement.id,
                reason_code="no_grounded_evidence",
            )
        ],
    )
    return artifact.model_dump(mode="json")


def _validation_payload() -> dict[str, object]:
    return ArtifactValidation(passed=True).model_dump(mode="json")


@pytest.mark.asyncio
async def test_artifact_record_round_trips_validated_output() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        run_id = await _create_run(
            test_session_factory,
            idempotency_key="artifact-round-trip-0001",
        )
        content = _artifact_payload(run_id)
        validation = _validation_payload()

        async with test_session_factory() as session:
            record = ArtifactRecord(
                run_id=run_id,
                content=content,
                validation=validation,
            )
            session.add(record)
            await session.commit()
            record_id = record.id

        async with test_session_factory() as session:
            saved_record = await session.scalar(
                select(ArtifactRecord).where(ArtifactRecord.id == record_id)
            )

        assert saved_record is not None
        assert saved_record.run_id == run_id
        assert ApplicationArtifact.model_validate(saved_record.content) == (
            ApplicationArtifact.model_validate(content)
        )
        assert ArtifactValidation.model_validate(saved_record.validation) == (
            ArtifactValidation.model_validate(validation)
        )
        assert saved_record.created_at is not None
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_artifact_record_rejects_unknown_run() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        unknown_run_id = uuid4()
        async with test_session_factory() as session:
            session.add(
                ArtifactRecord(
                    run_id=unknown_run_id,
                    content=_artifact_payload(unknown_run_id),
                    validation=_validation_payload(),
                )
            )

            with pytest.raises(IntegrityError):
                await session.commit()

            await session.rollback()
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_artifact_record_rejects_second_record_for_same_run() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        run_id = await _create_run(
            test_session_factory,
            idempotency_key="artifact-unique-run-0001",
        )
        records = [
            ArtifactRecord(
                run_id=run_id,
                content=_artifact_payload(run_id),
                validation=_validation_payload(),
            )
            for _ in range(2)
        ]

        async with test_session_factory() as session:
            session.add_all(records)

            with pytest.raises(IntegrityError) as exc_info:
                await session.commit()

            assert "artifact_records.run_id" in str(exc_info.value.orig)
            await session.rollback()
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_deleting_run_deletes_its_artifact_record() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        run_id = await _create_run(
            test_session_factory,
            idempotency_key="artifact-delete-cascade-0001",
        )
        async with test_session_factory() as session:
            session.add(
                ArtifactRecord(
                    run_id=run_id,
                    content=_artifact_payload(run_id),
                    validation=_validation_payload(),
                )
            )
            await session.commit()

        async with test_session_factory() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            await session.delete(run)
            await session.commit()

        async with test_session_factory() as session:
            saved_records = list((await session.scalars(select(ArtifactRecord))).all())

        assert saved_records == []
    finally:
        await test_engine.dispose()
