from uuid import UUID

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import Base, build_engine, build_session_factory, get_session
from app.main import app
from app.models.document import Document


@pytest.mark.asyncio
async def test_create_document_returns_201_and_persists_document() -> None:
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
                "/api/v1/workspaces/workspace-1/documents",
                json={
                    "name": "resume.txt",
                    "content": "Built a FastAPI application.",
                },
            )

        assert response.status_code == 201

        body = response.json()
        assert body["workspace_id"] == "workspace-1"
        assert body["name"] == "resume.txt"
        assert body["content"] == "Built a FastAPI application."

        document_id = UUID(body["id"])

        async with test_session_factory() as session:
            result = await session.execute(
                select(Document).where(
                    Document.id == document_id,
                    Document.workspace_id == "workspace-1",
                )
            )
            stored_document = result.scalar_one()

        assert stored_document.name == "resume.txt"
    finally:
        app.dependency_overrides.pop(get_session, None)
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_get_document_is_scoped_to_workspace() -> None:
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
                "/api/v1/workspaces/workspace-1/documents",
                json={
                    "name": "resume.txt",
                    "content": "Built a FastAPI application.",
                },
            )
            assert create_response.status_code == 201

            document_id = create_response.json()["id"]

            owner_response = await client.get(
                f"/api/v1/workspaces/workspace-1/documents/{document_id}"
            )
            other_workspace_response = await client.get(
                f"/api/v1/workspaces/workspace-2/documents/{document_id}"
            )

        assert owner_response.status_code == 200
        assert owner_response.json()["id"] == document_id
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
                "name": "resume.txt",
                "content": "   ",
            },
        ),
        (
            "bad workspace",
            {
                "name": "resume.txt",
                "content": "Built a FastAPI application.",
            },
        ),
    ],
)
async def test_create_document_rejects_invalid_request(
    workspace_id: str,
    payload: dict[str, str],
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/v1/workspaces/{workspace_id}/documents",
            json=payload,
        )

    assert response.status_code == 422