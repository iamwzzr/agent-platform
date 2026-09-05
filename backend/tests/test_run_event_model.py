from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import Base, build_engine, build_session_factory
from app.models.agent_run import AgentRun
from app.models.job import Job
from app.models.run_event import RunEvent


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
        )
        session.add(run)
        await session.commit()
        return run.id


@pytest.mark.asyncio
async def test_run_events_round_trip_in_sequence_order() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        run_id = await _create_run(
            test_session_factory,
            idempotency_key="event-round-trip-0001",
        )
        events = [
            RunEvent(
                run_id=run_id,
                sequence=1,
                kind="running",
                data={"attempt": 1},
            ),
            RunEvent(
                run_id=run_id,
                sequence=0,
                kind="queued",
            ),
        ]

        async with test_session_factory() as session:
            session.add_all(events)
            await session.commit()

        async with test_session_factory() as session:
            saved_events = list(
                (
                    await session.scalars(
                        select(RunEvent)
                        .where(RunEvent.run_id == run_id)
                        .order_by(RunEvent.sequence)
                    )
                ).all()
            )

        assert [event.sequence for event in saved_events] == [0, 1]
        assert [event.kind for event in saved_events] == ["queued", "running"]
        assert [event.data for event in saved_events] == [{}, {"attempt": 1}]
        assert all(event.created_at is not None for event in saved_events)
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_run_event_rejects_unknown_run() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        orphan_event = RunEvent(
            run_id=uuid4(),
            sequence=0,
            kind="queued",
        )

        async with test_session_factory() as session:
            session.add(orphan_event)

            with pytest.raises(IntegrityError):
                await session.commit()

            await session.rollback()
    finally:
        await test_engine.dispose()


@pytest.mark.parametrize(
    ("sequence", "kind", "constraint_name"),
    [
        (-1, "queued", "ck_run_events_sequence_non_negative"),
        (0, "   ", "ck_run_events_kind_not_blank"),
    ],
)
@pytest.mark.asyncio
async def test_run_event_rejects_invalid_fields(
    sequence: int,
    kind: str,
    constraint_name: str,
) -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        run_id = await _create_run(
            test_session_factory,
            idempotency_key=f"invalid-event-{constraint_name}-0001",
        )
        invalid_event = RunEvent(
            run_id=run_id,
            sequence=sequence,
            kind=kind,
        )

        async with test_session_factory() as session:
            session.add(invalid_event)

            with pytest.raises(IntegrityError) as exc_info:
                await session.commit()

            assert constraint_name in str(exc_info.value.orig)
            await session.rollback()
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_run_event_rejects_duplicate_sequence_for_same_run() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        run_id = await _create_run(
            test_session_factory,
            idempotency_key="duplicate-event-sequence-0001",
        )
        events = [
            RunEvent(run_id=run_id, sequence=0, kind="queued"),
            RunEvent(run_id=run_id, sequence=0, kind="running"),
        ]

        async with test_session_factory() as session:
            session.add_all(events)

            with pytest.raises(IntegrityError):
                await session.commit()

            await session.rollback()
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_run_event_sequence_is_scoped_to_run() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        first_run_id = await _create_run(
            test_session_factory,
            idempotency_key="first-event-sequence-0001",
        )
        second_run_id = await _create_run(
            test_session_factory,
            idempotency_key="second-event-sequence-0001",
        )
        events = [
            RunEvent(run_id=first_run_id, sequence=0, kind="queued"),
            RunEvent(run_id=second_run_id, sequence=0, kind="queued"),
        ]

        async with test_session_factory() as session:
            session.add_all(events)
            await session.commit()

        async with test_session_factory() as session:
            saved_events = list((await session.scalars(select(RunEvent))).all())

        assert len(saved_events) == 2
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_deleting_run_deletes_its_events() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        run_id = await _create_run(
            test_session_factory,
            idempotency_key="delete-run-events-0001",
        )
        async with test_session_factory() as session:
            session.add(RunEvent(run_id=run_id, sequence=0, kind="queued"))
            await session.commit()

        async with test_session_factory() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            await session.delete(run)
            await session.commit()

        async with test_session_factory() as session:
            saved_events = list((await session.scalars(select(RunEvent))).all())

        assert saved_events == []
    finally:
        await test_engine.dispose()
