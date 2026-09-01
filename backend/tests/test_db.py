import pytest
from sqlalchemy import text

from app.db import build_engine, build_session_factory


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