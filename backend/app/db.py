from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import Settings


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url)


def build_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_tables(target_engine: AsyncEngine) -> None:
    from app import models as _models  # noqa: F401

    async with target_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


settings = Settings()
engine = build_engine(settings.database_url)
session_factory = build_session_factory(engine)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
