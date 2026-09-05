import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx2
import pytest
from openai import APIConnectionError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.graph import InvalidRetrievedEvidenceError
from app.application_executor import ApplicationGraphRunExecutor
from app.db import Base, build_engine, build_session_factory
from app.models.agent_run import AgentRun
from app.models.artifact_record import ArtifactRecord
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.job import Job
from app.models.run_event import RunEvent
from app.openai_provider import ProviderResponseError
from app.providers import DeterministicMockProvider
from app.rag.retrieval import RetrievedChunk
from app.run_execution import RunExecutionLeaseLostError
from app.run_service import AgentRunService, RunNotResumableError
from app.schemas.artifact import ApplicationArtifact, Requirement


class RecoveringProvider(DeterministicMockProvider):
    def __init__(self) -> None:
        self.fail_draft = True
        self.draft_calls = 0

    async def draft_artifact(self, **kwargs: object) -> ApplicationArtifact:
        self.draft_calls += 1
        if self.fail_draft:
            raise APIConnectionError(
                request=httpx2.Request(
                    "POST",
                    "https://api.openai.com/v1/responses",
                )
            )
        return await super().draft_artifact(**kwargs)  # type: ignore[arg-type]


class PermanentFailureProvider(DeterministicMockProvider):
    def __init__(self) -> None:
        self.draft_calls = 0

    async def draft_artifact(self, **_: object) -> ApplicationArtifact:
        self.draft_calls += 1
        raise ProviderResponseError("private-provider-output-marker")


class InvalidGroundingProvider(DeterministicMockProvider):
    def __init__(self) -> None:
        self.draft_calls = 0
        self.revise_calls = 0

    async def draft_artifact(
        self,
        *,
        run_id: UUID,
        requirements: object,
        evidence: object,
    ) -> ApplicationArtifact:
        del evidence
        self.draft_calls += 1
        return ApplicationArtifact(
            run_id=run_id,
            requirements=requirements,  # type: ignore[arg-type]
        )

    async def revise_artifact(self, **kwargs: object) -> ApplicationArtifact:
        self.revise_calls += 1
        return await self.draft_artifact(
            run_id=kwargs["run_id"],  # type: ignore[arg-type]
            requirements=kwargs["requirements"],
            evidence=kwargs["evidence"],
        )


async def _seed_input(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID]:
    job = Job(
        workspace_id="workspace-1",
        title="Backend Engineer",
        description="Build Python FastAPI services.",
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
async def test_resume_uses_durable_completed_node_checkpoints(
    tmp_path: Path,
) -> None:
    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'resume.db'}")
    session_factory = build_session_factory(engine)
    provider = RecoveringProvider()
    requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )
    extract = AsyncMock(return_value=[requirement])
    retrieve = AsyncMock(return_value=[])
    verify = AsyncMock()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        job_id, document_id = await _seed_input(session_factory)
        first_executor = ApplicationGraphRunExecutor(
            session_factory=session_factory,
            provider=provider,
            extract_requirements=extract,
            retrieve_chunks_for_requirement=retrieve,
            verify_retrieved_chunk=verify,
            provider_retry_max_attempts=3,
            provider_retry_initial_delay_seconds=0,
        )
        first_service = AgentRunService(
            session_factory=session_factory,
            executor=first_executor,
        )

        with pytest.raises(APIConnectionError):
            await first_service.start_run(
                workspace_id="workspace-1",
                job_id=job_id,
                document_ids=[document_id],
                idempotency_key="durable-resume-0001",
            )

        async with session_factory() as session:
            run = await session.scalar(
                select(AgentRun).where(
                    AgentRun.idempotency_key == "durable-resume-0001"
                )
            )
        assert run is not None
        assert run.status == "failed"
        assert run.retryable is True
        assert run.error_code == "connection_error"
        assert set(run.state_json) >= {"requirements", "retrieved_evidence"}
        assert "artifact" not in run.state_json
        assert provider.draft_calls == 3

        provider.fail_draft = False
        second_executor = ApplicationGraphRunExecutor(
            session_factory=session_factory,
            provider=provider,
            extract_requirements=extract,
            retrieve_chunks_for_requirement=retrieve,
            verify_retrieved_chunk=verify,
            provider_retry_max_attempts=3,
            provider_retry_initial_delay_seconds=0,
        )
        second_service = AgentRunService(
            session_factory=session_factory,
            executor=second_executor,
        )
        resumed_run_id = await second_service.resume_run(
            workspace_id="workspace-1",
            run_id=run.id,
        )

        async with session_factory() as session:
            resumed_run = await session.get(AgentRun, resumed_run_id)
            events = list(
                (
                    await session.scalars(
                        select(RunEvent)
                        .where(RunEvent.run_id == resumed_run_id)
                        .order_by(RunEvent.sequence)
                    )
                ).all()
            )
            artifact_records = list(
                (
                    await session.scalars(
                        select(ArtifactRecord).where(
                            ArtifactRecord.run_id == resumed_run_id
                        )
                    )
                ).all()
            )

        assert resumed_run is not None
        assert resumed_run.status == "succeeded"
        assert resumed_run.attempt_count == 2
        assert resumed_run.retryable is False
        assert resumed_run.error_code is None
        assert extract.await_count == 1
        assert retrieve.await_count == 1
        assert provider.draft_calls == 4
        assert verify.await_count == 0
        assert len(artifact_records) == 1
        assert [event.sequence for event in events] == list(range(len(events)))
        assert [event.kind for event in events].count("resumed") == 1
        assert [event.kind for event in events].count("succeeded") == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_permanent_provider_failure_is_not_retried_or_resumable(
    tmp_path: Path,
) -> None:
    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'permanent.db'}")
    session_factory = build_session_factory(engine)
    provider = PermanentFailureProvider()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        job_id, document_id = await _seed_input(session_factory)
        executor = ApplicationGraphRunExecutor(
            session_factory=session_factory,
            provider=provider,
            retrieve_chunks_for_requirement=AsyncMock(return_value=[]),
            provider_retry_initial_delay_seconds=0,
        )
        service = AgentRunService(
            session_factory=session_factory,
            executor=executor,
        )

        with pytest.raises(ProviderResponseError):
            await service.start_run(
                workspace_id="workspace-1",
                job_id=job_id,
                document_ids=[document_id],
                idempotency_key="permanent-failure-0001",
            )

        async with session_factory() as session:
            run = await session.scalar(
                select(AgentRun).where(
                    AgentRun.idempotency_key == "permanent-failure-0001"
                )
            )
            event_data = list(
                (
                    await session.scalars(
                        select(RunEvent.data).where(RunEvent.run_id == run.id)
                    )
                ).all()
            )

        assert run is not None
        assert run.status == "failed"
        assert run.retryable is False
        assert run.error_code == "invalid_response"
        assert provider.draft_calls == 1
        assert "private-provider-output-marker" not in repr(event_data)
        assert "private-provider-output-marker" not in repr(run.state_json)
        with pytest.raises(RunNotResumableError):
            await service.resume_run(
                workspace_id="workspace-1",
                run_id=run.id,
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_production_composition_persists_a_grounded_mock_artifact(
    tmp_path: Path,
) -> None:
    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'composition.db'}")
    session_factory = build_session_factory(engine)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        job_id, document_id = await _seed_input(session_factory)
        executor = ApplicationGraphRunExecutor(
            session_factory=session_factory,
            provider=DeterministicMockProvider(),
            provider_retry_initial_delay_seconds=0,
        )
        service = AgentRunService(
            session_factory=session_factory,
            executor=executor,
        )

        run_id = await service.start_run(
            workspace_id="workspace-1",
            job_id=job_id,
            document_ids=[document_id],
            idempotency_key="production-composition-0001",
        )

        async with session_factory() as session:
            run = await session.get(AgentRun, run_id)
            record = await session.scalar(
                select(ArtifactRecord).where(ArtifactRecord.run_id == run_id)
            )

        assert run is not None
        assert run.status == "succeeded"
        assert run.current_node == "terminal"
        assert record is not None
        artifact = ApplicationArtifact.model_validate(record.content)
        assert len(artifact.claims) == 1
        assert artifact.claims[0].citation_chunk_ids
        assert artifact.gaps == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_revision_exhaustion_does_not_publish_an_artifact(
    tmp_path: Path,
) -> None:
    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'exhaustion.db'}")
    session_factory = build_session_factory(engine)
    provider = InvalidGroundingProvider()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        job_id, document_id = await _seed_input(session_factory)
        executor = ApplicationGraphRunExecutor(
            session_factory=session_factory,
            provider=provider,
            retrieve_chunks_for_requirement=AsyncMock(return_value=[]),
            max_revisions=1,
            provider_retry_initial_delay_seconds=0,
        )
        service = AgentRunService(
            session_factory=session_factory,
            executor=executor,
        )

        run_id = await service.start_run(
            workspace_id="workspace-1",
            job_id=job_id,
            document_ids=[document_id],
            idempotency_key="revision-exhaustion-0001",
        )

        async with session_factory() as session:
            run = await session.get(AgentRun, run_id)
            records = list(
                (
                    await session.scalars(
                        select(ArtifactRecord).where(ArtifactRecord.run_id == run_id)
                    )
                ).all()
            )

        assert run is not None
        assert run.status == "validation_failed"
        assert run.revision_count == 1
        assert provider.draft_calls == 2
        assert provider.revise_calls == 1
        assert records == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_production_verifier_rejects_a_forged_in_scope_chunk(
    tmp_path: Path,
) -> None:
    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'forged-chunk.db'}")
    session_factory = build_session_factory(engine)
    provider = DeterministicMockProvider()
    provider.draft_artifact = AsyncMock(wraps=provider.draft_artifact)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        job_id, document_id = await _seed_input(session_factory)
        executor = ApplicationGraphRunExecutor(
            session_factory=session_factory,
            provider=provider,
            retrieve_chunks_for_requirement=AsyncMock(
                return_value=[
                    RetrievedChunk(
                        chunk_id=UUID(int=1),
                        document_id=document_id,
                        workspace_id="workspace-1",
                        position=0,
                        content="forged content",
                        score=1.0,
                    )
                ]
            ),
            provider_retry_initial_delay_seconds=0,
        )
        service = AgentRunService(
            session_factory=session_factory,
            executor=executor,
        )

        with pytest.raises(
            InvalidRetrievedEvidenceError,
            match="does not match persisted evidence",
        ):
            await service.start_run(
                workspace_id="workspace-1",
                job_id=job_id,
                document_ids=[document_id],
                idempotency_key="forged-chunk-0001",
            )

        provider.draft_artifact.assert_not_awaited()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_executor_that_loses_token_cannot_persist_a_checkpoint(
    tmp_path: Path,
) -> None:
    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'checkpoint-fence.db'}")
    session_factory = build_session_factory(engine)
    extract_started = asyncio.Event()
    release_extract = asyncio.Event()
    requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )

    async def extract(_: str) -> list[Requirement]:
        extract_started.set()
        await release_extract.wait()
        return [requirement]

    provider = DeterministicMockProvider()
    provider.draft_artifact = AsyncMock(wraps=provider.draft_artifact)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        job_id, document_id = await _seed_input(session_factory)
        original_token = uuid4()
        run = AgentRun(
            workspace_id="workspace-1",
            job_id=job_id,
            idempotency_key="checkpoint-fence-0001",
            document_ids=[str(document_id)],
            status="running",
            provider=provider.name,
            model=provider.model_name,
            lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            execution_token=original_token,
        )
        async with session_factory() as session:
            session.add(run)
            await session.commit()
            run_id = run.id

        executor = ApplicationGraphRunExecutor(
            session_factory=session_factory,
            provider=provider,
            extract_requirements=extract,
            retrieve_chunks_for_requirement=AsyncMock(return_value=[]),
            provider_retry_initial_delay_seconds=0,
        )
        task = asyncio.create_task(executor(run_id, original_token))
        await extract_started.wait()

        replacement_token = uuid4()
        async with session_factory() as session:
            claimed_run = await session.get(AgentRun, run_id)
            assert claimed_run is not None
            claimed_run.execution_token = replacement_token
            await session.commit()

        release_extract.set()
        with pytest.raises(RunExecutionLeaseLostError):
            await task

        async with session_factory() as session:
            fenced_run = await session.get(AgentRun, run_id)
            events = list(
                (
                    await session.scalars(
                        select(RunEvent).where(RunEvent.run_id == run_id)
                    )
                ).all()
            )
        assert fenced_run is not None
        assert fenced_run.execution_token == replacement_token
        assert fenced_run.current_node is None
        assert fenced_run.state_json == {}
        assert events == []
        provider.draft_artifact.assert_not_awaited()
    finally:
        release_extract.set()
        await engine.dispose()
