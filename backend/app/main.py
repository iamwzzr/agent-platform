from fastapi import FastAPI

app = FastAPI()

@app.get("/api/v1/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "ok"}
