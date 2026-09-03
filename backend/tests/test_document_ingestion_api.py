from uuid import UUID

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import Base, build_engine, build_session_factory, get_session
from app.main import app
from app.models.document_chunk import DocumentChunk


@pytest.mark.asyncio
async def test_ingest_document_returns_200_and_persists_chunks() -> None:
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

            ingest_response = await client.post(
                f"/api/v1/workspaces/workspace-1/documents/{document_id}/ingest"
            )

        assert ingest_response.status_code == 200

        body = ingest_response.json()
        assert body["document_id"] == document_id
        assert body["workspace_id"] == "workspace-1"
        assert body["chunk_count"] == 1
        assert len(body["chunks"]) == 1

        chunk = body["chunks"][0]
        UUID(chunk["id"])
        assert chunk["document_id"] == document_id
        assert chunk["workspace_id"] == "workspace-1"
        assert chunk["position"] == 0
        assert chunk["content"] == "Built a FastAPI application."

        async with test_session_factory() as session:
            result = await session.execute(
                select(DocumentChunk).where(
                    DocumentChunk.document_id == UUID(document_id)
                )
            )
            saved_chunks = list(result.scalars().all())

        assert len(saved_chunks) == 1
        assert str(saved_chunks[0].id) == chunk["id"]
    finally:
        app.dependency_overrides.pop(get_session, None)
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_ingest_document_is_scoped_to_workspace() -> None:
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

            ingest_response = await client.post(
                f"/api/v1/workspaces/workspace-2/documents/{document_id}/ingest"
            )

        assert ingest_response.status_code == 404
        assert ingest_response.json() == {"detail": "Document not found"}

        async with test_session_factory() as session:
            result = await session.execute(select(DocumentChunk))
            saved_chunks = list(result.scalars().all())

        assert saved_chunks == []
    finally:
        app.dependency_overrides.pop(get_session, None)
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_ingest_document_retry_preserves_chunk_ids() -> None:
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

            ingest_path = (
                f"/api/v1/workspaces/workspace-1/documents/{document_id}/ingest"
            )

            first_response = await client.post(ingest_path)
            second_response = await client.post(ingest_path)

        assert first_response.status_code == 200
        assert second_response.status_code == 200
        assert second_response.json() == first_response.json()

        first_chunk_id = first_response.json()["chunks"][0]["id"]

        async with test_session_factory() as session:
            result = await session.execute(
                select(DocumentChunk).where(
                    DocumentChunk.document_id == UUID(document_id)
                )
            )
            saved_chunks = list(result.scalars().all())

        assert len(saved_chunks) == 1
        assert str(saved_chunks[0].id) == first_chunk_id
    finally:
        app.dependency_overrides.pop(get_session, None)
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_ingest_document_returns_409_for_conflicting_chunks() -> None:
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

            conflicting_chunk = DocumentChunk(
                workspace_id="workspace-1",
                document_id=UUID(document_id),
                position=0,
                content="Incorrect stored content.",
            )

            async with test_session_factory() as session:
                session.add(conflicting_chunk)
                await session.commit()
                conflicting_chunk_id = conflicting_chunk.id

            ingest_response = await client.post(
                f"/api/v1/workspaces/workspace-1/documents/{document_id}/ingest"
            )

        assert ingest_response.status_code == 409
        assert ingest_response.json() == {"detail": "Document ingestion conflict"}

        async with test_session_factory() as session:
            result = await session.execute(
                select(DocumentChunk).where(
                    DocumentChunk.document_id == UUID(document_id)
                )
            )
            saved_chunks = list(result.scalars().all())

        assert len(saved_chunks) == 1
        assert saved_chunks[0].id == conflicting_chunk_id
        assert saved_chunks[0].content == "Incorrect stored content."
    finally:
        app.dependency_overrides.pop(get_session, None)
        await test_engine.dispose()
