from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.documents import router as documents_router
from app.api.jobs import router as jobs_router
from app.api.retrieval import router as retrieval_router
from app.db import create_tables, engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        await create_tables(engine)
        yield
    finally:
        await engine.dispose()


app = FastAPI(lifespan=lifespan)
app.include_router(jobs_router)
app.include_router(documents_router)
app.include_router(retrieval_router)


@app.get("/api/v1/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "ok"}
