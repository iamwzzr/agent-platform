from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import ANY, AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.runs import get_run_service
from app.db import Base, build_engine, build_session_factory, get_session
from app.main import app
from app.models.agent_run import AgentRun
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.job import Job
from app.models.run_event import RunEvent
from app.openai_provider import ProviderResponseError
from app.run_execution import RunExecutionResult
from app.run_service import AgentRunService
from app.schemas.artifact import (
    ApplicationArtifact,
    ArtifactValidation,
    Gap,
    Requirement,
)


def _successful_result(run_id: UUID, _: UUID) -> RunExecutionResult:
    requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )
    return RunExecutionResult(
        run_id=run_id,
        workspace_id="workspace-1",
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


async def _seed_inputs(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID]:
    job = Job(
        workspace_id="workspace-1",
        title="Python Backend Engineer",
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


@asynccontextmanager
async def _run_api_client(
    tmp_path: Path,
    executor: AsyncMock,
) -> AsyncIterator[
    tuple[
        AsyncClient,
        async_sessionmaker[AsyncSession],
        UUID,
        UUID,
    ]
]:
    database_path = tmp_path / f"run-api-{uuid4()}.db"
    test_engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    test_session_factory = build_session_factory(test_engine)
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    job_id, document_id = await _seed_inputs(test_session_factory)
    service = AgentRunService(
        session_factory=test_session_factory,
        executor=executor,
    )

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with test_session_factory() as session:
            yield session

    def override_get_run_service() -> AgentRunService:
        return service

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_run_service] = override_get_run_service

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client, test_session_factory, job_id, document_id
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_run_service, None)
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_run_api_creates_queries_and_deduplicates_successful_run(
    tmp_path: Path,
) -> None:
    executor = AsyncMock(side_effect=_successful_result)
    async with _run_api_client(tmp_path, executor) as (
        client,
        _,
        job_id,
        document_id,
    ):
        request_path = f"/api/v1/workspaces/workspace-1/jobs/{job_id}/runs"
        request_kwargs = {
            "headers": {"Idempotency-Key": "run-api-success-0001"},
            "json": {"document_ids": [str(document_id)]},
        }
        first_response = await client.post(request_path, **request_kwargs)
        duplicate_response = await client.post(request_path, **request_kwargs)

        assert first_response.status_code == 202
        assert duplicate_response.status_code == 202
        assert duplicate_response.json()["id"] == first_response.json()["id"]
        executor.assert_awaited_once()

        accepted_body = first_response.json()
        assert accepted_body["status"] == "running"
        assert accepted_body["artifact"] is None
        assert [event["kind"] for event in accepted_body["events"]] == [
            "queued",
            "running",
        ]

        body = duplicate_response.json()
        assert body["workspace_id"] == "workspace-1"
        assert body["job_id"] == str(job_id)
        assert body["document_ids"] == [str(document_id)]
        assert body["status"] == "succeeded"
        assert body["retryable"] is False
        assert body["artifact"]["content"]["run_id"] == body["id"]
        assert body["artifact"]["validation"]["passed"] is True
        assert [event["kind"] for event in body["events"]] == [
            "queued",
            "running",
            "succeeded",
        ]
        for timestamp in (
            body["created_at"],
            body["started_at"],
            body["finished_at"],
            body["artifact"]["created_at"],
            *(event["created_at"] for event in body["events"]),
        ):
            assert timestamp.endswith(("Z", "+00:00"))

        query_response = await client.get(
            f"/api/v1/workspaces/workspace-1/runs/{body['id']}"
        )
        cross_workspace_response = await client.get(
            f"/api/v1/workspaces/workspace-2/runs/{body['id']}"
        )
        resume_response = await client.post(
            f"/api/v1/workspaces/workspace-1/runs/{body['id']}/resume"
        )

        assert query_response.status_code == 200
        assert query_response.json()["events"] == body["events"]
        assert query_response.json()["artifact"] == body["artifact"]
        assert cross_workspace_response.status_code == 404
        assert cross_workspace_response.json() == {"detail": "Run not found"}
        assert resume_response.status_code == 409
        assert resume_response.json() == {"detail": "Run cannot be resumed"}


@pytest.mark.asyncio
async def test_run_api_resumes_only_retryable_failed_run(
    tmp_path: Path,
) -> None:
    executor = AsyncMock(side_effect=_successful_result)
    async with _run_api_client(tmp_path, executor) as (
        client,
        session_factory,
        job_id,
        document_id,
    ):
        failed_run = AgentRun(
            workspace_id="workspace-1",
            job_id=job_id,
            idempotency_key="run-api-resume-0001",
            document_ids=[str(document_id)],
            status="failed",
            provider="mock",
            model="deterministic-mock-v1",
            attempt_count=1,
            retryable=True,
            error_code="connection_error",
        )
        async with session_factory() as session:
            session.add(failed_run)
            await session.flush()
            session.add_all(
                [
                    RunEvent(run_id=failed_run.id, sequence=0, kind="queued"),
                    RunEvent(run_id=failed_run.id, sequence=1, kind="running"),
                    RunEvent(
                        run_id=failed_run.id,
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
        run_id = failed_run.id

        cross_workspace_response = await client.post(
            f"/api/v1/workspaces/workspace-2/runs/{run_id}/resume"
        )
        response = await client.post(
            f"/api/v1/workspaces/workspace-1/runs/{run_id}/resume"
        )

        assert cross_workspace_response.status_code == 404
        assert response.status_code == 202
        accepted_body = response.json()
        assert accepted_body["status"] == "running"
        assert accepted_body["lease_expires_at"].endswith(("Z", "+00:00"))

        completed_response = await client.get(
            f"/api/v1/workspaces/workspace-1/runs/{run_id}"
        )
        assert completed_response.status_code == 200
        body = completed_response.json()
        assert body["id"] == str(run_id)
        assert body["status"] == "succeeded"
        assert body["attempt_count"] == 2
        assert [event["kind"] for event in body["events"]] == [
            "queued",
            "running",
            "failed",
            "resumed",
            "succeeded",
        ]
        executor.assert_awaited_once_with(run_id, ANY)


@pytest.mark.asyncio
async def test_run_api_maps_request_conflicts_and_validation_errors(
    tmp_path: Path,
) -> None:
    executor = AsyncMock(side_effect=_successful_result)
    async with _run_api_client(tmp_path, executor) as (
        client,
        session_factory,
        job_id,
        document_id,
    ):
        path = f"/api/v1/workspaces/workspace-1/jobs/{job_id}/runs"
        empty_response = await client.post(
            path,
            headers={"Idempotency-Key": "run-api-invalid-0001"},
            json={"document_ids": []},
        )
        missing_job_response = await client.post(
            f"/api/v1/workspaces/workspace-1/jobs/{uuid4()}/runs",
            headers={"Idempotency-Key": "run-api-missing-0001"},
            json={"document_ids": [str(document_id)]},
        )

        second_job = Job(
            workspace_id="workspace-1",
            title="Platform Engineer",
            description="Operate Kubernetes clusters.",
        )
        async with session_factory() as session:
            session.add(second_job)
            await session.commit()
        shared_headers = {"Idempotency-Key": "run-api-conflict-0001"}
        first_response = await client.post(
            path,
            headers=shared_headers,
            json={"document_ids": [str(document_id)]},
        )
        conflict_response = await client.post(
            f"/api/v1/workspaces/workspace-1/jobs/{second_job.id}/runs",
            headers=shared_headers,
            json={"document_ids": [str(document_id)]},
        )

        assert empty_response.status_code == 422
        assert missing_job_response.status_code == 404
        assert missing_job_response.json() == {"detail": "Run input not found"}
        assert first_response.status_code == 202
        assert conflict_response.status_code == 409
        assert conflict_response.json() == {
            "detail": "Run request conflicts with existing state"
        }
        executor.assert_awaited_once()


@pytest.mark.parametrize(
    ("executor_error", "expected_error_code"),
    [
        (
            ProviderResponseError("private-provider-output-marker"),
            "invalid_response",
        ),
        (RuntimeError("private-provider-output-marker"), "unknown_error"),
    ],
)
@pytest.mark.asyncio
async def test_run_api_does_not_expose_executor_failure(
    tmp_path: Path,
    executor_error: Exception,
    expected_error_code: str,
) -> None:
    executor = AsyncMock(side_effect=executor_error)
    async with _run_api_client(tmp_path, executor) as (
        client,
        _,
        job_id,
        document_id,
    ):
        response = await client.post(
            f"/api/v1/workspaces/workspace-1/jobs/{job_id}/runs",
            headers={"Idempotency-Key": "run-api-failed-0001"},
            json={"document_ids": [str(document_id)]},
        )

        assert response.status_code == 202
        assert response.json()["status"] == "running"
        assert "private-provider-output-marker" not in response.text

        result = await client.get(
            "/api/v1/workspaces/workspace-1/runs/" + response.json()["id"]
        )
        assert result.status_code == 200
        assert result.json()["status"] == "failed"
        assert result.json()["error_code"] == expected_error_code
        assert "private-provider-output-marker" not in result.text


@pytest.mark.asyncio
async def test_run_api_sanitizes_executor_identity_mismatch(
    tmp_path: Path,
) -> None:
    executor = AsyncMock(side_effect=_successful_result)
    async with _run_api_client(tmp_path, executor) as (
        client,
        session_factory,
        job_id,
        document_id,
    ):
        run = AgentRun(
            workspace_id="workspace-1",
            job_id=job_id,
            idempotency_key="run-api-executor-mismatch-0001",
            document_ids=[str(document_id)],
            provider="openai",
            model="private-model-marker",
        )
        async with session_factory() as session:
            session.add(run)
            await session.flush()
            session.add(RunEvent(run_id=run.id, sequence=0, kind="queued"))
            await session.commit()
            run_id = run.id

        response = await client.post(
            f"/api/v1/workspaces/workspace-1/jobs/{job_id}/runs",
            headers={"Idempotency-Key": "run-api-executor-mismatch-0001"},
            json={"document_ids": [str(document_id)]},
        )

        assert response.status_code == 503
        assert response.json() == {"detail": "Run execution failed"}
        assert "private-model-marker" not in response.text
        executor.assert_not_awaited()

        async with session_factory() as session:
            preserved = await session.get(AgentRun, run_id)
        assert preserved is not None
        assert preserved.status == "queued"
