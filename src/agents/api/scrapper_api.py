from fastapi import FastAPI
from pydantic import BaseModel
from src.agents.scrapper_agent import main as scrapper_main

app = FastAPI(title="Scrapper Agent", version="1.0")


class RunRequest(BaseModel):
    limit: int = 20


class RunResponse(BaseModel):
    status: str
    scraped: int
    message: str


@app.get("/health")
def health():
    return {"status": "ok", "agent": "scrapper"}


@app.post("/run", response_model=RunResponse)
async def run(req: RunRequest):
    try:
        await scrapper_main(limit=req.limit)
        return RunResponse(
            status="done",
            scraped=req.limit,
            message="Scraping terminé"
        )
    except Exception as e:
        return RunResponse(
            status="error",
            scraped=0,
            message=str(e)
        )