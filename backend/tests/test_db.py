import pytest
from sqlalchemy import inspect, text

from app.db import build_engine, build_session_factory, create_tables


@pytest.mark.asyncio
async def test_session_can_execute_query() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    try:
        async with test_session_factory() as session:
            result = await session.execute(text("SELECT 1"))

            assert result.scalar_one() == 1
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_create_tables_creates_domain_tables() -> None:
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")

    try:
        await create_tables(test_engine)

        async with test_engine.connect() as connection:
            table_names = await connection.run_sync(
                lambda sync_connection: inspect(
                    sync_connection
                ).get_table_names()
            )

        assert "jobs" in table_names
        assert "documents" in table_names
    finally:
        await test_engine.dispose()
