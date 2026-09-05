from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event, text
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


def _enable_sqlite_foreign_keys(
    dbapi_connection: Any,
    _: Any,
) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def build_engine(database_url: str) -> AsyncEngine:
    engine = create_async_engine(database_url)

    if engine.dialect.name == "sqlite":
        event.listen(
            engine.sync_engine,
            "connect",
            _enable_sqlite_foreign_keys,
        )

    return engine


def build_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_tables(target_engine: AsyncEngine) -> None:
    from app import models as _models  # noqa: F401

    async with target_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        if target_engine.dialect.name == "sqlite":
            # create_all() cannot add the Stage 7 composite uniqueness rule to
            # an existing jobs table. This compatible index makes the
            # AgentRun composite foreign key valid without deleting user data.
            await connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_jobs_id_workspace_id ON jobs (id, workspace_id)"
                )
            )


settings = Settings()
engine = build_engine(settings.database_url)
session_factory = build_session_factory(engine)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
