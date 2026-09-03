import pytest
from httpx2 import ASGITransport, AsyncClient

from app.db import Base, build_engine, build_session_factory, get_session
from app.main import app


@pytest.mark.asyncio
async def test_retrieval_api_returns_traceable_results() -> None:
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
            relevant_document_response = await client.post(
                "/api/v1/workspaces/workspace-1/documents",
                json={
                    "name": "resume.txt",
                    "content": "Built Python FastAPI services.",
                },
            )
            unrelated_document_response = await client.post(
                "/api/v1/workspaces/workspace-1/documents",
                json={
                    "name": "notes.txt",
                    "content": "Java database administration.",
                },
            )

            assert relevant_document_response.status_code == 201
            assert unrelated_document_response.status_code == 201

            relevant_document_id = relevant_document_response.json()["id"]
            unrelated_document_id = unrelated_document_response.json()["id"]

            relevant_ingest_response = await client.post(
                f"/api/v1/workspaces/workspace-1/"
                f"documents/{relevant_document_id}/ingest"
            )
            unrelated_ingest_response = await client.post(
                f"/api/v1/workspaces/workspace-1/"
                f"documents/{unrelated_document_id}/ingest"
            )

            assert relevant_ingest_response.status_code == 200
            assert unrelated_ingest_response.status_code == 200

            retrieval_response = await client.post(
                "/api/v1/workspaces/workspace-1/retrieval",
                json={
                    "query": "Python FastAPI",
                    "document_ids": [
                        relevant_document_id,
                        unrelated_document_id,
                    ],
                    "top_k": 5,
                    "min_score": 0.0,
                },
            )

        assert retrieval_response.status_code == 200

        body = retrieval_response.json()
        assert body["query"] == "Python FastAPI"
        assert body["count"] == 1
        assert len(body["results"]) == 1

        result = body["results"][0]
        expected_chunk = relevant_ingest_response.json()["chunks"][0]

        assert result["chunk_id"] == expected_chunk["id"]
        assert result["document_id"] == relevant_document_id
        assert result["workspace_id"] == "workspace-1"
        assert result["position"] == 0
        assert result["content"] == "Built Python FastAPI services."
        assert result["score"] > 0.0
    finally:
        app.dependency_overrides.pop(get_session, None)
        await test_engine.dispose()


@pytest.mark.parametrize(
    "payload",
    [
        {"query": "   "},
        {
            "query": "Python",
            "top_k": 0,
        },
        {
            "query": "Python",
            "min_score": 1.01,
        },
    ],
)
@pytest.mark.asyncio
async def test_retrieval_api_rejects_invalid_request(
    payload: dict[str, object],
) -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

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
                "/api/v1/workspaces/workspace-1/retrieval",
                json=payload,
            )

        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_session, None)
        await test_engine.dispose()

@pytest.mark.asyncio
async def test_retrieval_api_rejects_cross_workspace_document() -> None:
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
            owned_response = await client.post(
                "/api/v1/workspaces/workspace-1/documents",
                json={
                    "name": "resume.txt",
                    "content": "Built Python FastAPI services.",
                },
            )
            foreign_response = await client.post(
                "/api/v1/workspaces/workspace-2/documents",
                json={
                    "name": "private.txt",
                    "content": "Private evidence.",
                },
            )

            owned_id = owned_response.json()["id"]
            foreign_id = foreign_response.json()["id"]

            await client.post(
                f"/api/v1/workspaces/workspace-1/"
                f"documents/{owned_id}/ingest"
            )

            response = await client.post(
                "/api/v1/workspaces/workspace-1/retrieval",
                json={
                    "query": "Python FastAPI",
                    "document_ids": [owned_id, foreign_id],
                },
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Document not found"
        }
    finally:
        app.dependency_overrides.pop(get_session, None)
        await test_engine.dispose()