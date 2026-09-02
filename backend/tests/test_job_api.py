from uuid import UUID

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import Base, build_engine, build_session_factory, get_session
from app.main import app
from app.models.job import Job


@pytest.mark.asyncio
async def test_create_job_returns_201_and_persists_job() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_get_session():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/workspaces/workspace-1/jobs",
                json={
                    "title": "Python Backend Engineer",
                    "description": "Build FastAPI services.",
                },
            )

        assert response.status_code == 201

        body = response.json()
        assert body["workspace_id"] == "workspace-1"
        assert body["title"] == "Python Backend Engineer"
        assert body["description"] == "Build FastAPI services."

        job_id = UUID(body["id"])

        async with test_session_factory() as session:
            result = await session.execute(
                select(Job).where(
                    Job.id == job_id,
                    Job.workspace_id == "workspace-1",
                )
            )
            stored_job = result.scalar_one()

        assert stored_job.title == "Python Backend Engineer"
    finally:
        app.dependency_overrides.pop(get_session, None)
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_get_job_is_scoped_to_workspace() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_get_session():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            create_response = await client.post(
                "/api/v1/workspaces/workspace-1/jobs",
                json={
                    "title": "Python Backend Engineer",
                    "description": "Build FastAPI services.",
                },
            )
            assert create_response.status_code == 201

            job_id = create_response.json()["id"]

            owner_response = await client.get(
                f"/api/v1/workspaces/workspace-1/jobs/{job_id}"
            )
            other_workspace_response = await client.get(
                f"/api/v1/workspaces/workspace-2/jobs/{job_id}"
            )

        assert owner_response.status_code == 200
        assert owner_response.json()["id"] == job_id
        assert other_workspace_response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_session, None)
        await test_engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("workspace_id", "payload"),
    [
        (
            "workspace-1",
            {
                "title": "   ",
                "description": "Build FastAPI services.",
            },
        ),
        (
            "bad workspace",
            {
                "title": "Python Backend Engineer",
                "description": "Build FastAPI services.",
            },
        ),
    ],
)
async def test_create_job_rejects_invalid_request(
    workspace_id: str,
    payload: dict[str, str],
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/v1/workspaces/{workspace_id}/jobs",
            json=payload,
        )

    assert response.status_code == 422