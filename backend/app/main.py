from fastapi import FastAPI

from app.api.jobs import router as jobs_router
from app.api.documents import router as documents_router

app = FastAPI()
app.include_router(jobs_router)
app.include_router(documents_router)


@app.get("/api/v1/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "ok"}
