from fastapi import FastAPI
from pydantic import BaseModel
from src.agents.marketing_agent import run_marketing

app = FastAPI(title="Marketing Agent", version="1.0")


class RunResponse(BaseModel):
    status:  str
    message: str
    insights: dict


@app.get("/health")
def health():
    return {"status": "ok", "agent": "marketing"}


@app.post("/run", response_model=RunResponse)
async def run():
    try:
        insights = await run_marketing()
        tier1_count = len(insights.get("tier1_companies", []))
        tier2_count = len(insights.get("tier2_companies", []))
        return RunResponse(
            status="done",
            message=f"Analyse terminée — {tier1_count} Tier1, {tier2_count} Tier2",
            insights=insights,
        )
    except Exception as e:
        return RunResponse(
            status="error",
            message=str(e),
            insights={},
        )