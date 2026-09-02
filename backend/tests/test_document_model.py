import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import Base, build_engine, build_session_factory
from app.models.document import Document


@pytest.mark.asyncio
async def test_document_can_round_trip_across_sessions() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        document = Document(
            workspace_id="workspace-1",
            name="resume.txt",
            content="Built a FastAPI application with automated tests.",
        )

        async with test_session_factory() as session:
            session.add(document)
            await session.commit()
            document_id = document.id

        async with test_session_factory() as session:
            result = await session.execute(
                select(Document).where(
                    Document.id == document_id,
                    Document.workspace_id == "workspace-1",
                )
            )
            saved_document = result.scalar_one()

        assert saved_document.name == "resume.txt"
        assert saved_document.content.startswith("Built a FastAPI")
        assert saved_document.created_at is not None
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_document_rejects_blank_content() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        invalid_document = Document(
            workspace_id="workspace-1",
            name="resume.txt",
            content="   ",
        )

        async with test_session_factory() as session:
            session.add(invalid_document)

            with pytest.raises(IntegrityError):
                await session.commit()

            await session.rollback()
    finally:
        await test_engine.dispose()