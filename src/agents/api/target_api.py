"""
Agent A2A — Target Searcher
Recherche de prospects B2B via DuckDuckGo + classification hybride.
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
    name="target_searcher",
    description=(
        "Recherche des entreprises cibles B2B en Europe via DuckDuckGo. "
        "Classification hybride (embedding + LLM). Déduplication vs SQLite/Neo4j."
    ),
    url="http://localhost:8001",
    version="1.0.0",
    capabilities=["data-output"],
    skills=[
        Skill(
            id="search_prospects",
            name="Recherche de prospects",
            description="Recherche, déduplique et classifie des entreprises industrielles",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_per_query": {
                        "type": "integer",
                        "description": "Nombre max de résultats par requête DDG",
                        "default": 5,
                    }
                },
            },
        )
    ],
)


async def handle_task(task: Task) -> Task:
    from src.agents.target_searcher import run_pipeline

    params = {}
    for msg in task.messages:
        for part in msg.parts:
            if isinstance(part, DataPart):
                params = part.data
            elif isinstance(part, dict) and part.get("type") == "data":
                params = part.get("data", {})

    max_per_query = params.get("max_per_query", 5)

    stats = await run_pipeline(max_per_query=max_per_query)
    saved = stats.get("saved", 0) if isinstance(stats, dict) else 0

    task.artifacts.append(
        Artifact(
            name="search_results",
            parts=[DataPart(data={"saved": saved, "stats": stats if isinstance(stats, dict) else {}})],
        )
    )
    task.messages.append(
        Message(role="agent", parts=[TextPart(text=f"{saved} prospects trouvés et sauvegardés")])
    )
    return task


app = create_a2a_app(AGENT_CARD, handle_task)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
