"""
Agent A2A — Scrapper Agent
Crawl multi-pages + extraction LLM + Neo4j + embeddings.
"""

from src.a2a.models import (
    AgentCard,
    Artifact,
    DataPart,
    Message,
    Skill,
    Task,
    TextPart,
)
from src.a2a.server import create_a2a_app

AGENT_CARD = AgentCard(
    name="scrapper_agent",
    description=(
        "Scrape les sites web des entreprises (contact, about, mentions légales). "
        "Extraction par LLM (email, téléphone, adresse, LinkedIn). "
        "Sauvegarde SQLite + Neo4j avec relations et embeddings."
    ),
    url="http://localhost:8002",
    version="1.0.0",
    capabilities=["data-output"],
    skills=[
        Skill(
            id="scrape_companies",
            name="Scraping d'entreprises",
            description="Scrape les entreprises pending et extrait les informations de contact",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Nombre max d'entreprises à scraper",
                        "default": 20,
                    }
                },
            },
        )
    ],
)


async def handle_task(task: Task) -> Task:
    from src.agents.scrapper_agent import main as scrapper_main

    params = {}
    for msg in task.messages:
        for part in msg.parts:
            if isinstance(part, DataPart):
                params = part.data
            elif isinstance(part, dict) and part.get("type") == "data":
                params = part.get("data", {})

    limit = params.get("limit", 20)

    result = await scrapper_main(limit=limit)
    scraped = result if isinstance(result, int) else 0

    task.artifacts.append(
        Artifact(
            name="scrape_results",
            parts=[DataPart(data={"scraped": scraped})],
        )
    )
    task.messages.append(
        Message(role="agent", parts=[TextPart(text=f"{scraped} entreprises scrapées")])
    )
    return task


app = create_a2a_app(AGENT_CARD, handle_task)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
