from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db_core import Base, build_engine, build_session_factory, create_tables

__all__ = [
    "Base",
    "build_engine",
    "build_session_factory",
    "create_tables",
    "engine",
    "get_session",
    "session_factory",
    "settings",
]

settings = Settings()
engine = build_engine(settings.database_url)
session_factory = build_session_factory(engine)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
