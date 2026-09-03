from uuid import uuid4

import pytest

from app.db import Base, build_engine, build_session_factory
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.rag.retrieval import RetrievalDocumentNotFoundError, retrieve_chunks


@pytest.mark.asyncio
async def test_retrieve_chunks_is_scoped_to_workspace() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        partial_document = Document(
            workspace_id="workspace-1",
            name="partial.txt",
            content="Python data analysis",
        )
        relevant_document = Document(
            workspace_id="workspace-1",
            name="relevant.txt",
            content="Built Python FastAPI services",
        )
        other_workspace_document = Document(
            workspace_id="workspace-2",
            name="private.txt",
            content="Python FastAPI",
        )

        async with test_session_factory() as session:
            session.add_all(
                [
                    partial_document,
                    relevant_document,
                    other_workspace_document,
                ]
            )
            await session.flush()

            partial_chunk = DocumentChunk(
                workspace_id="workspace-1",
                document_id=partial_document.id,
                position=0,
                content=partial_document.content,
            )
            relevant_chunk = DocumentChunk(
                workspace_id="workspace-1",
                document_id=relevant_document.id,
                position=0,
                content=relevant_document.content,
            )
            other_workspace_chunk = DocumentChunk(
                workspace_id="workspace-2",
                document_id=other_workspace_document.id,
                position=0,
                content=other_workspace_document.content,
            )

            session.add_all(
                [
                    partial_chunk,
                    relevant_chunk,
                    other_workspace_chunk,
                ]
            )
            await session.commit()

        async with test_session_factory() as session:
            retrieved = await retrieve_chunks(
                session,
                workspace_id="workspace-1",
                query="Python FastAPI",
                top_k=5,
            )

        assert [item.chunk_id for item in retrieved] == [
            relevant_chunk.id,
            partial_chunk.id,
        ]
        assert all(item.workspace_id == "workspace-1" for item in retrieved)
        assert other_workspace_chunk.id not in {item.chunk_id for item in retrieved}
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_retrieve_chunks_respects_document_scope() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        selected_document = Document(
            workspace_id="workspace-1",
            name="selected.txt",
            content="Python experience",
        )
        excluded_document = Document(
            workspace_id="workspace-1",
            name="excluded.txt",
            content="Python FastAPI",
        )

        async with test_session_factory() as session:
            session.add_all(
                [
                    selected_document,
                    excluded_document,
                ]
            )
            await session.flush()

            selected_chunk = DocumentChunk(
                workspace_id="workspace-1",
                document_id=selected_document.id,
                position=0,
                content=selected_document.content,
            )
            excluded_chunk = DocumentChunk(
                workspace_id="workspace-1",
                document_id=excluded_document.id,
                position=0,
                content=excluded_document.content,
            )

            session.add_all(
                [
                    selected_chunk,
                    excluded_chunk,
                ]
            )
            await session.commit()

        async with test_session_factory() as session:
            selected_results = await retrieve_chunks(
                session,
                workspace_id="workspace-1",
                query="Python FastAPI",
                document_ids=[selected_document.id],
            )
            empty_results = await retrieve_chunks(
                session,
                workspace_id="workspace-1",
                query="Python FastAPI",
                document_ids=[],
            )

        assert [item.chunk_id for item in selected_results] == [selected_chunk.id]
        assert selected_results[0].document_id == selected_document.id
        assert excluded_chunk.id not in {item.chunk_id for item in selected_results}
        assert empty_results == []
    finally:
        await test_engine.dispose()

@pytest.mark.asyncio
async def test_retrieve_chunks_rejects_missing_document() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        document = Document(
            workspace_id="workspace-1",
            name="resume.txt",
            content="Built Python FastAPI services.",
        )

        async with test_session_factory() as session:
            session.add(document)
            await session.flush()

            chunk = DocumentChunk(
                workspace_id="workspace-1",
                document_id=document.id,
                position=0,
                content=document.content,
            )
            session.add(chunk)
            await session.commit()

            owned_document_id = document.id

        async with test_session_factory() as session:
            with pytest.raises(
                RetrievalDocumentNotFoundError,
                match="Document not found",
            ):
                await retrieve_chunks(
                    session,
                    workspace_id="workspace-1",
                    query="Python FastAPI",
                    document_ids=[
                        owned_document_id,
                        uuid4(),
                    ],
                )
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_retrieve_chunks_accepts_document_without_chunks() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        document = Document(
            workspace_id="workspace-1",
            name="not-ingested.txt",
            content="This document has not been ingested.",
        )

        async with test_session_factory() as session:
            session.add(document)
            await session.commit()
            document_id = document.id

        async with test_session_factory() as session:
            results = await retrieve_chunks(
                session,
                workspace_id="workspace-1",
                query="Python",
                document_ids=[document_id],
            )

        assert results == []
    finally:
        await test_engine.dispose()