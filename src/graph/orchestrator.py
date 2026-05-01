"""
Orchestrateur A2A — pilote les 3 agents via le protocole Agent-to-Agent.

Flux : target_searcher → scrapper → marketing
Chaque noeud LangGraph communique avec un agent distant via A2AClient.
"""

from langgraph.graph import StateGraph, END
from loguru import logger

from src.a2a.client import A2AClient
from src.state import AgentState

AGENTS = {
    "target":    "http://localhost:8001",
    "scrapper":  "http://localhost:8002",
    "marketing": "http://localhost:8003",
}


# ============================================================
# NOEUDS — communication A2A avec les agents
# ============================================================

async def node_target_searcher(state: AgentState) -> AgentState:
    logger.info("[Orchestrator] → A2A target_searcher")
    if _step_callback:
        _step_callback("target_searcher", 15)
    try:
        client = A2AClient(AGENTS["target"], timeout=300.0)

        card = await client.get_agent_card()
        logger.info(f"[A2A] Découvert: {card.name} — {card.description}")

        task = await client.send_task(
            data={"max_per_query": state["max_per_query"]}
        )

        result_data = client.extract_data(task)
        result_text = client.extract_text(task)
        found = result_data.get("saved", 0)

        logger.info(f"[A2A] target_searcher → {task.state.value}: {result_text}")

        return {
            **state,
            "prospects_found": found,
            "messages": state["messages"] + [
                {"role": "target_searcher", "content": result_text, "task_id": task.id}
            ],
        }
    except Exception as e:
        logger.error(f"[Orchestrator] target_searcher A2A error: {e}")
        return {
            **state,
            "errors": state["errors"] + [f"target_searcher: {e}"],
        }


async def node_scrapper(state: AgentState) -> AgentState:
    logger.info("[Orchestrator] → A2A scrapper_agent")
    if _step_callback:
        _step_callback("scrapper", 40)
    try:
        client = A2AClient(AGENTS["scrapper"], timeout=600.0)

        card = await client.get_agent_card()
        logger.info(f"[A2A] Découvert: {card.name} — {card.description}")

        task = await client.send_task(
            data={"limit": state["limit_scraping"]}
        )

        result_data = client.extract_data(task)
        result_text = client.extract_text(task)
        scraped = result_data.get("scraped", 0)

        logger.info(f"[A2A] scrapper → {task.state.value}: {result_text}")

        return {
            **state,
            "prospects_scraped": scraped,
            "messages": state["messages"] + [
                {"role": "scrapper", "content": result_text, "task_id": task.id}
            ],
        }
    except Exception as e:
        logger.error(f"[Orchestrator] scrapper A2A error: {e}")
        return {
            **state,
            "errors": state["errors"] + [f"scrapper: {e}"],
        }


async def node_marketing(state: AgentState) -> AgentState:
    logger.info("[Orchestrator] → A2A marketing_agent")
    if _step_callback:
        _step_callback("marketing", 75)
    try:
        client = A2AClient(AGENTS["marketing"], timeout=300.0)

        card = await client.get_agent_card()
        logger.info(f"[A2A] Découvert: {card.name} — {card.description}")

        task = await client.send_task()

        result_data = client.extract_data(task)
        result_text = client.extract_text(task)

        logger.info(f"[A2A] marketing → {task.state.value}: {result_text}")

        return {
            **state,
            "marketing_insights": result_data if isinstance(result_data, dict) else {},
            "messages": state["messages"] + [
                {"role": "marketing", "content": result_text, "task_id": task.id}
            ],
        }
    except Exception as e:
        logger.error(f"[Orchestrator] marketing A2A error: {e}")
        return {
            **state,
            "errors": state["errors"] + [f"marketing: {e}"],
        }


# ============================================================
# CONDITIONS
# ============================================================

def should_scrape(state: AgentState) -> str:
    if state.get("prospects_found", 0) > 0:
        return "scrape"
    if state.get("errors"):
        return "end"
    return "scrape"


def should_run_marketing(state: AgentState) -> str:
    if state.get("prospects_scraped", 0) > 0:
        return "marketing"
    return "end"


# ============================================================
# GRAPHE LangGraph
# ============================================================

def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("target_searcher", node_target_searcher)
    graph.add_node("scrapper",        node_scrapper)
    graph.add_node("marketing",       node_marketing)

    graph.set_entry_point("target_searcher")

    graph.add_conditional_edges(
        "target_searcher",
        should_scrape,
        {"scrape": "scrapper", "end": END},
    )

    graph.add_conditional_edges(
        "scrapper",
        should_run_marketing,
        {"marketing": "marketing", "end": END},
    )

    graph.add_edge("marketing", END)

    return graph.compile()


# ============================================================
# Callback et Pipeline
# ============================================================

_step_callback = None


def set_step_callback(fn):
    """Permet à Flask de recevoir les changements d'étape en temps réel."""
    global _step_callback
    _step_callback = fn


async def run_pipeline(max_per_query: int = 5, limit_scraping: int = 20):
    """Lance le pipeline complet via A2A : Searcher → Scrapper → Marketing."""
    graph = build_graph()

    initial_state: AgentState = {
        "status":             "running",
        "prospects_found":    0,
        "prospects_scraped":  0,
        "competitors_found":  0,
        "marketing_insights": {},
        "report_path":        "",
        "messages":           [],
        "errors":             [],
        "max_per_query":      max_per_query,
        "limit_scraping":     limit_scraping,
    }

    final_state = await graph.ainvoke(initial_state)

    logger.info("=== PIPELINE A2A TERMINÉ ===")
    logger.info(f"Prospects trouvés  : {final_state['prospects_found']}")
    logger.info(f"Prospects scrapés  : {final_state['prospects_scraped']}")
    for msg in final_state["messages"]:
        logger.info(f"  [{msg['role']}] {msg['content']}")
    if final_state["errors"]:
        logger.warning(f"Erreurs : {final_state['errors']}")

    return final_state
