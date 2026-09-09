from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from inspect import signature
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import db, providers
from app.api import runs as runs_api
from app.config import Settings
from app.db import Base, build_engine, build_session_factory, get_session
from app.main import app
from app.models.agent_run import AgentRun
from app.models.artifact_record import ArtifactRecord
from app.models.job import Job
from app.models.run_event import RunEvent
from app.providers import DeterministicMockProvider
from app.rag.retrieval import retrieve_chunks

USAGE_FIELDS = {
    "saved_jobs",
    "jobs_with_runs",
    "runs",
    "succeeded_runs",
    "validation_failed_runs",
    "failed_runs",
    "active_runs",
    "published_artifacts",
    "jobs_with_published_artifacts",
    "mock_runs",
    "openai_runs",
    "other_provider_runs",
    "artifacts_with_resume_bullets",
    "gap_only_artifacts",
    "resume_bullets",
    "gaps",
    "cover_letters",
}


@pytest.fixture(autouse=True)
def public_mock_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        db,
        "settings",
        Settings(
            _env_file=None,
            llm_provider="mock",
            agent_max_revisions=2,
            provider_retry_max_attempts=3,
            provider_retry_initial_delay_seconds=0.5,
        ),
    )


@asynccontextmanager
async def overview_client() -> AsyncIterator[
    tuple[AsyncClient, async_sessionmaker[AsyncSession]]
]:
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    factory = build_session_factory(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, factory
    finally:
        app.dependency_overrides.pop(get_session, None)
        await engine.dispose()


def make_job(workspace_id: str = "workspace-1") -> Job:
    return Job(
        id=uuid4(),
        workspace_id=workspace_id,
        title="private-job-marker",
        description="private-description-marker",
    )


def make_run(job: Job, status: str, provider: str = "mock") -> AgentRun:
    return AgentRun(
        id=uuid4(),
        workspace_id=job.workspace_id,
        job_id=job.id,
        idempotency_key=str(uuid4()),
        status=status,
        provider=provider,
        model="historical-model-marker",
        lease_expires_at=(
            datetime.now(UTC) + timedelta(minutes=5) if status == "running" else None
        ),
        execution_token=uuid4() if status == "running" else None,
    )


def artifact_content(run_id: UUID, *, bullets: bool = False) -> dict[str, object]:
    content: dict[str, object] = {
        "run_id": str(run_id),
        "requirements": [
            {"id": "req-1", "text": "private-requirement-marker", "priority": "high"}
        ],
        "gaps": [{"requirement_id": "req-1", "reason_code": "no_grounded_evidence"}],
    }
    if bullets:
        content.update(
            claims=[
                {
                    "id": "claim-1",
                    "text": "private-claim-marker",
                    "requirement_ids": ["req-1"],
                    "citation_chunk_ids": [str(uuid4())],
                }
            ],
            resume_bullets=[
                {"text": "private-bullet-marker", "claim_ids": ["claim-1"]},
                {"text": "private-second-bullet-marker", "claim_ids": ["claim-1"]},
            ],
            cover_letter="private-letter-marker",
            gaps=[],
        )
    return content


@pytest.mark.asyncio
async def test_overview_empty_workspace_returns_zero_usage_and_public_configuration():
    async with overview_client() as (client, _):
        response = await client.get("/api/v1/workspaces/new-workspace/overview")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"workspace_id", "generated_at", "configuration", "usage"}
    assert payload["workspace_id"] == "new-workspace"
    assert datetime.fromisoformat(payload["generated_at"]).tzinfo is not None
    assert payload["usage"] == dict.fromkeys(USAGE_FIELDS, 0)
    assert payload["configuration"] == {
        "provider": "mock",
        "model": DeterministicMockProvider.model_name,
        "max_revisions": 2,
        "provider_retry_max_attempts": 3,
        "provider_retry_initial_delay_seconds": 0.5,
        "retrieval_method": "deterministic_sparse_cosine",
        "retrieval_top_k": signature(retrieve_chunks).parameters["top_k"].default,
    }


@pytest.mark.asyncio
async def test_overview_scopes_runs_packages_providers_and_materials_without_event_fanout():
    async with overview_client() as (client, factory):
        job, second_job, unused_job = make_job(), make_job(), make_job()
        other_job = make_job("workspace-2")
        gap_run = make_run(job, "succeeded")
        gap_run.attempt_count = 3  # Resumed execution remains the same run/package.
        gap_run.revision_count = 2
        bullet_run = make_run(job, "succeeded", "openai")
        empty_run = make_run(second_job, "succeeded", "legacy-provider")
        queued_run = make_run(second_job, "queued", "legacy-provider")
        running_run = make_run(second_job, "running")
        invalid_run = make_run(second_job, "validation_failed")
        failed_run = make_run(second_job, "failed", "openai")
        other_run = make_run(other_job, "succeeded", "openai")
        run_records = [
            gap_run,
            bullet_run,
            empty_run,
            queued_run,
            running_run,
            invalid_run,
            failed_run,
            other_run,
        ]
        async with factory() as session:
            session.add_all([job, second_job, unused_job, other_job])
            await session.flush()
            session.add_all(run_records)
            await session.flush()
            for run in run_records:
                session.add_all(
                    RunEvent(
                        run_id=run.id,
                        sequence=sequence,
                        kind="checkpoint",
                        data={"private-event-marker": "private-content-marker"},
                    )
                    for sequence in range(4)
                )
            for run in (gap_run, bullet_run, invalid_run, failed_run, other_run):
                session.add(
                    ArtifactRecord(
                        run_id=run.id,
                        content=artifact_content(run.id, bullets=run is not gap_run),
                        validation={"passed": run is not invalid_run},
                    )
                )
            await session.commit()

        first = await client.get("/api/v1/workspaces/workspace-1/overview")
        second = await client.get("/api/v1/workspaces/workspace-1/overview")

    expected_usage = {
        "saved_jobs": 3,
        "jobs_with_runs": 2,
        "runs": 7,
        "succeeded_runs": 3,
        "validation_failed_runs": 1,
        "failed_runs": 1,
        "active_runs": 2,
        "published_artifacts": 2,
        "jobs_with_published_artifacts": 1,
        "mock_runs": 3,
        "openai_runs": 2,
        "other_provider_runs": 2,
        "artifacts_with_resume_bullets": 1,
        "gap_only_artifacts": 1,
        "resume_bullets": 2,
        "gaps": 1,
        "cover_letters": 1,
    }
    assert first.status_code == second.status_code == 200
    assert first.json()["usage"] == second.json()["usage"] == expected_usage
    assert "private-" not in first.text
    assert "historical-model-marker" not in first.text


@pytest.mark.asyncio
@pytest.mark.parametrize("additional_material", ["claims", "cover_letter"])
async def test_gap_only_excludes_packages_with_claims_or_cover_letters(
    additional_material: str,
):
    async with overview_client() as (client, factory):
        job = make_job()
        run = make_run(job, "succeeded")
        content = artifact_content(run.id)
        bullet_content = artifact_content(run.id, bullets=True)
        content[additional_material] = bullet_content[additional_material]
        async with factory() as session:
            session.add(job)
            await session.flush()
            session.add(run)
            await session.flush()
            session.add(
                ArtifactRecord(
                    run_id=run.id, content=content, validation={"passed": True}
                )
            )
            await session.commit()
        response = await client.get("/api/v1/workspaces/workspace-1/overview")

    assert response.status_code == 200
    usage = response.json()["usage"]
    assert usage["published_artifacts"] == 1
    assert usage["gaps"] == 1
    assert usage["gap_only_artifacts"] == usage["artifacts_with_resume_bullets"] == 0
    assert usage["cover_letters"] == int(additional_material == "cover_letter")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption",
    [
        "content_list",
        "content_fields",
        "validation_list",
        "validation_fields",
        "passed_string",
        "not_passed",
        "run_id",
    ],
)
async def test_overview_conservatively_skips_malformed_or_unvalidated_artifacts(
    corruption: str,
):
    async with overview_client() as (client, factory):
        job = make_job()
        run = make_run(job, "succeeded")
        content = artifact_content(run.id)
        validation: object = {"passed": True}
        if corruption == "content_list":
            content = ["private-corruption-marker"]
        elif corruption == "content_fields":
            content["resume_bullets"] = "private-corruption-marker"
        elif corruption == "validation_list":
            validation = ["private-corruption-marker"]
        elif corruption == "validation_fields":
            validation = {
                "passed": True,
                "invalid_citation_chunk_ids": "private-marker",
            }
        elif corruption == "passed_string":
            validation = {"passed": "true"}
        elif corruption == "not_passed":
            validation = {"passed": False}
        else:
            content["run_id"] = str(uuid4())
        async with factory() as session:
            session.add(job)
            await session.flush()
            session.add(run)
            await session.flush()
            session.add(
                ArtifactRecord(run_id=run.id, content=content, validation=validation)
            )
            await session.commit()
        response = await client.get("/api/v1/workspaces/workspace-1/overview")

    assert response.status_code == 200
    usage = response.json()["usage"]
    assert usage["succeeded_runs"] == 1
    assert usage["published_artifacts"] == usage["jobs_with_published_artifacts"] == 0
    assert usage["gaps"] == usage["resume_bullets"] == usage["cover_letters"] == 0
    assert "private-" not in response.text


@pytest.mark.asyncio
async def test_configuration_uses_deployment_whitelist_without_constructing_client(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        db,
        "settings",
        Settings(
            _env_file=None,
            llm_provider="openai",
            openai_model="  deployment-model  ",
            openai_api_key="private-api-key-marker",
            database_url="postgresql://private-user:private-password@private-host/db",
            agent_max_revisions=5,
            provider_retry_max_attempts=4,
            provider_retry_initial_delay_seconds=1.25,
        ),
    )
    forbidden_factory = Mock(side_effect=AssertionError("must not construct provider"))
    monkeypatch.setattr(providers, "OpenAIResponsesProvider", forbidden_factory)
    monkeypatch.setattr(runs_api, "build_agent_provider", forbidden_factory)
    monkeypatch.setattr(
        Settings, "model_dump", Mock(side_effect=AssertionError("must use whitelist"))
    )
    async with overview_client() as (client, _):
        response = await client.get("/api/v1/workspaces/workspace-1/overview")

    assert response.status_code == 200
    assert response.json()["configuration"] == {
        "provider": "openai",
        "model": "deployment-model",
        "max_revisions": 5,
        "provider_retry_max_attempts": 4,
        "provider_retry_initial_delay_seconds": 1.25,
        "retrieval_method": "deterministic_sparse_cosine",
        "retrieval_top_k": 5,
    }
    forbidden_factory.assert_not_called()
    for private_value in (
        "private-",
        "api_key",
        "database_url",
        "SecretStr",
        "postgresql",
    ):
        assert private_value not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "workspace_id", ["has%20space", "-leading", "_leading", "a" * 101]
)
async def test_overview_rejects_invalid_workspace_id(workspace_id: str):
    async with overview_client() as (client, _):
        response = await client.get(f"/api/v1/workspaces/{workspace_id}/overview")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_overview_keeps_counts_consistent_when_a_run_completes_during_read():
    async with overview_client() as (client, factory):
        job = make_job()
        run = make_run(job, "queued")
        async with factory() as session:
            session.add(job)
            await session.flush()
            session.add(run)
            await session.commit()

        async with factory() as reader:
            original_stream = reader.stream

            async def stream_after_run_completes(statement):
                # The previous implementation read run totals before reaching
                # stream(), mixing queued-run counts with the new artifact.
                async with factory() as writer:
                    await writer.execute(
                        update(AgentRun)
                        .where(AgentRun.id == run.id)
                        .values(status="succeeded")
                    )
                    writer.add(
                        ArtifactRecord(
                            run_id=run.id,
                            content=artifact_content(run.id),
                            validation={"passed": True},
                        )
                    )
                    await writer.commit()
                return await original_stream(statement)

            reader.scalar = AsyncMock(wraps=reader.scalar)
            reader.execute = AsyncMock(wraps=reader.execute)
            reader.stream = AsyncMock(side_effect=stream_after_run_completes)

            async def override_get_session():
                yield reader

            app.dependency_overrides[get_session] = override_get_session
            response = await client.get("/api/v1/workspaces/workspace-1/overview")
            reader.scalar.assert_not_awaited()
            reader.execute.assert_not_awaited()
            reader.stream.assert_awaited_once()

    assert response.status_code == 200
    usage = response.json()["usage"]
    assert usage["runs"] == usage["succeeded_runs"] == usage["published_artifacts"] == 1
    assert usage["active_runs"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["query", "iteration", "close"])
async def test_overview_returns_fixed_service_error_without_database_details(
    failure_stage: str,
):
    session = AsyncMock(spec=AsyncSession)
    database_error = SQLAlchemyError("private-sql-and-content-marker")
    rows = AsyncMock()
    rows.__aiter__.return_value = []
    session.stream.return_value = rows
    if failure_stage == "query":
        session.stream.side_effect = database_error
    elif failure_stage == "iteration":
        rows.__aiter__.side_effect = database_error
    else:
        rows.close.side_effect = database_error

    async def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/workspaces/workspace-1/overview")
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert response.status_code == 503
    assert response.json() == {"detail": "Workspace overview unavailable"}


def test_default_run_service_passes_current_revision_and_retry_limits(
    monkeypatch: pytest.MonkeyPatch,
):
    settings = Settings(
        _env_file=None,
        llm_provider="mock",
        agent_max_revisions=4,
        provider_retry_max_attempts=5,
        provider_retry_initial_delay_seconds=1.5,
    )
    provider = Mock()
    executor = Mock()
    executor_factory = Mock(return_value=executor)
    service_factory = Mock()
    monkeypatch.setattr(runs_api, "settings", settings)
    monkeypatch.setattr(runs_api, "build_agent_provider", Mock(return_value=provider))
    monkeypatch.setattr(runs_api, "ApplicationGraphRunExecutor", executor_factory)
    monkeypatch.setattr(runs_api, "AgentRunService", service_factory)

    # Exercise the constructor without disturbing another test's cached service.
    runs_api._build_default_run_service.__wrapped__()

    executor_factory.assert_called_once_with(
        session_factory=runs_api.session_factory,
        provider=provider,
        max_revisions=4,
        provider_retry_max_attempts=5,
        provider_retry_initial_delay_seconds=1.5,
    )
    service_factory.assert_called_once_with(
        session_factory=runs_api.session_factory,
        executor=executor,
    )
