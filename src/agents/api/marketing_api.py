"""
Agent A2A — Marketing Agent
Analyse des prospects + plan de ciblage + pitchs personnalisés.
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
    name="marketing_agent",
    description=(
        "Analyse les entreprises Tier 1 et Tier 2 depuis Neo4j. "
        "Génère un plan de ciblage priorisé et des pitchs commerciaux "
        "personnalisés pour chaque prospect (email + LinkedIn)."
    ),
    url="http://localhost:8003",
    version="1.0.0",
    capabilities=["data-output"],
    skills=[
        Skill(
            id="analyze_prospects",
            name="Analyse marketing",
            description="Analyse les prospects et génère un plan de ciblage avec pitchs",
            inputSchema={"type": "object", "properties": {}},
        )
    ],
)


async def handle_task(task: Task) -> Task:
    from src.agents.marketing_agent import run_marketing

    insights = await run_marketing()

    tier1_count = len(insights.get("tier1_companies", []))
    tier2_count = len(insights.get("tier2_companies", []))
    pitch_count = len(insights.get("pitches", []))

    task.artifacts.append(
        Artifact(
            name="marketing_insights",
            parts=[DataPart(data=insights)],
        )
    )
    task.messages.append(
        Message(
            role="agent",
            parts=[
                TextPart(
                    text=(
                        f"Analyse terminée — {tier1_count} Tier 1, {tier2_count} Tier 2, "
                        f"{pitch_count} pitchs générés"
                    )
                )
            ],
        )
    )
    return task


app = create_a2a_app(AGENT_CARD, handle_task)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
