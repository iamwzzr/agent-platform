from fastapi import FastAPI

from app.api.jobs import router as jobs_router

app = FastAPI()
app.include_router(jobs_router)


@app.get("/api/v1/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "ok"}
