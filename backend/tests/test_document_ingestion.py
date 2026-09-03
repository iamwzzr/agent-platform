import pytest
from sqlalchemy import select

from app.db import Base, build_engine, build_session_factory
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.rag.ingestion import (
    DocumentIngestionConflictError,
    DocumentNotFoundError,
    ingest_document,
)


@pytest.mark.asyncio
async def test_ingest_document_creates_ordered_chunks() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        document = Document(
            workspace_id="workspace-1",
            name="resume.txt",
            content="one two three four five six seven",
        )

        async with test_session_factory() as session:
            session.add(document)
            await session.commit()
            document_id = document.id

        async with test_session_factory() as session:
            chunks = await ingest_document(
                session,
                workspace_id="workspace-1",
                document_id=document_id,
                chunk_size_words=4,
                overlap_words=1,
            )
            await session.commit()

        async with test_session_factory() as session:
            result = await session.execute(
                select(DocumentChunk)
                .where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.workspace_id == "workspace-1",
                )
                .order_by(DocumentChunk.position)
            )
            saved_chunks = list(result.scalars().all())

        assert [chunk.position for chunk in saved_chunks] == [0, 1]
        assert [chunk.content for chunk in saved_chunks] == [
            "one two three four",
            "four five six seven",
        ]
        assert [chunk.id for chunk in chunks] == [chunk.id for chunk in saved_chunks]
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_ingest_document_rejects_other_workspace() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        document = Document(
            workspace_id="workspace-1",
            name="resume.txt",
            content="one two three four",
        )

        async with test_session_factory() as session:
            session.add(document)
            await session.commit()
            document_id = document.id

        async with test_session_factory() as session:
            with pytest.raises(DocumentNotFoundError):
                await ingest_document(
                    session,
                    workspace_id="workspace-2",
                    document_id=document_id,
                    chunk_size_words=4,
                    overlap_words=1,
                )

        async with test_session_factory() as session:
            result = await session.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )

        assert list(result.scalars().all()) == []
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_ingest_document_is_idempotent() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        document = Document(
            workspace_id="workspace-1",
            name="resume.txt",
            content="one two three four five six seven",
        )

        async with test_session_factory() as session:
            session.add(document)
            await session.commit()
            document_id = document.id

        async with test_session_factory() as session:
            first_chunks = await ingest_document(
                session,
                workspace_id="workspace-1",
                document_id=document_id,
                chunk_size_words=4,
                overlap_words=1,
            )
            await session.commit()
            first_ids = [chunk.id for chunk in first_chunks]

        async with test_session_factory() as session:
            second_chunks = await ingest_document(
                session,
                workspace_id="workspace-1",
                document_id=document_id,
                chunk_size_words=4,
                overlap_words=1,
            )
            await session.commit()
            second_ids = [chunk.id for chunk in second_chunks]

        async with test_session_factory() as session:
            result = await session.execute(
                select(DocumentChunk)
                .where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.workspace_id == "workspace-1",
                )
                .order_by(DocumentChunk.position)
            )
            saved_chunks = list(result.scalars().all())

        assert len(saved_chunks) == 2
        assert second_ids == first_ids
        assert [chunk.id for chunk in saved_chunks] == first_ids
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_ingest_document_rejects_conflicting_chunks() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        document = Document(
            workspace_id="workspace-1",
            name="resume.txt",
            content="one two three four five six seven",
        )

        async with test_session_factory() as session:
            session.add(document)
            await session.commit()
            document_id = document.id

        async with test_session_factory() as session:
            first_chunks = await ingest_document(
                session,
                workspace_id="workspace-1",
                document_id=document_id,
                chunk_size_words=4,
                overlap_words=1,
            )
            await session.commit()
            first_ids = [chunk.id for chunk in first_chunks]
            first_contents = [chunk.content for chunk in first_chunks]

        async with test_session_factory() as session:
            with pytest.raises(DocumentIngestionConflictError):
                await ingest_document(
                    session,
                    workspace_id="workspace-1",
                    document_id=document_id,
                    chunk_size_words=3,
                    overlap_words=1,
                )

        async with test_session_factory() as session:
            result = await session.execute(
                select(DocumentChunk)
                .where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.workspace_id == "workspace-1",
                )
                .order_by(DocumentChunk.position)
            )
            saved_chunks = list(result.scalars().all())

        assert [chunk.id for chunk in saved_chunks] == first_ids
        assert [chunk.content for chunk in saved_chunks] == first_contents
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_ingest_document_does_not_commit_callers_transaction() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        document = Document(
            workspace_id="workspace-1",
            name="resume.txt",
            content="one two three four",
        )

        async with test_session_factory() as session:
            session.add(document)
            await session.commit()
            document_id = document.id

        async with test_session_factory() as session:
            await ingest_document(
                session,
                workspace_id="workspace-1",
                document_id=document_id,
                chunk_size_words=4,
                overlap_words=1,
            )
            await session.rollback()

        async with test_session_factory() as session:
            result = await session.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )

        assert list(result.scalars().all()) == []
    finally:
        await test_engine.dispose()
