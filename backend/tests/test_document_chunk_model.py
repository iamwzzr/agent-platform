from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import Base, build_engine, build_session_factory
from app.models.document import Document
from app.models.document_chunk import DocumentChunk


@pytest.mark.asyncio
async def test_document_chunks_round_trip_in_position_order() -> None:
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

        chunks = [
            DocumentChunk(
                workspace_id="workspace-1",
                document_id=document_id,
                position=0,
                content="one two three four",
            ),
            DocumentChunk(
                workspace_id="workspace-1",
                document_id=document_id,
                position=1,
                content="four five six seven",
            ),
        ]

        async with test_session_factory() as session:
            session.add_all(chunks)
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
        assert all(chunk.document_id == document_id for chunk in saved_chunks)
        assert all(chunk.created_at is not None for chunk in saved_chunks)
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_document_chunk_rejects_unknown_document() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        orphan_chunk = DocumentChunk(
            workspace_id="workspace-1",
            document_id=uuid4(),
            position=0,
            content="This chunk has no source document.",
        )

        async with test_session_factory() as session:
            session.add(orphan_chunk)

            with pytest.raises(IntegrityError):
                await session.commit()

            await session.rollback()
    finally:
        await test_engine.dispose()


@pytest.mark.parametrize(
    ("workspace_id", "position", "content"),
    [
        ("   ", 0, "valid content"),
        ("workspace-1", -1, "valid content"),
        ("workspace-1", 0, "   "),
    ],
)
@pytest.mark.asyncio
async def test_document_chunk_rejects_invalid_fields(
    workspace_id: str,
    position: int,
    content: str,
) -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        document = Document(
            workspace_id="workspace-1",
            name="resume.txt",
            content="Source document content.",
        )

        async with test_session_factory() as session:
            session.add(document)
            await session.commit()
            document_id = document.id

        invalid_chunk = DocumentChunk(
            workspace_id=workspace_id,
            document_id=document_id,
            position=position,
            content=content,
        )

        async with test_session_factory() as session:
            session.add(invalid_chunk)

            with pytest.raises(IntegrityError):
                await session.commit()

            await session.rollback()
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_document_chunk_rejects_duplicate_position() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        document = Document(
            workspace_id="workspace-1",
            name="resume.txt",
            content="Source document content.",
        )

        async with test_session_factory() as session:
            session.add(document)
            await session.commit()
            document_id = document.id

        chunks = [
            DocumentChunk(
                workspace_id="workspace-1",
                document_id=document_id,
                position=0,
                content="first chunk",
            ),
            DocumentChunk(
                workspace_id="workspace-1",
                document_id=document_id,
                position=0,
                content="duplicate position",
            ),
        ]

        async with test_session_factory() as session:
            session.add_all(chunks)

            with pytest.raises(IntegrityError):
                await session.commit()

            await session.rollback()
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_document_chunk_rejects_workspace_mismatch() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        document = Document(
            workspace_id="workspace-1",
            name="resume.txt",
            content="Source document content.",
        )

        async with test_session_factory() as session:
            session.add(document)
            await session.commit()
            document_id = document.id

        mismatched_chunk = DocumentChunk(
            workspace_id="workspace-2",
            document_id=document_id,
            position=0,
            content="Chunk with a false workspace.",
        )

        async with test_session_factory() as session:
            session.add(mismatched_chunk)

            with pytest.raises(IntegrityError):
                await session.commit()

            await session.rollback()
    finally:
        await test_engine.dispose()
