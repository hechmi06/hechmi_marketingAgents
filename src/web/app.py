import asyncio
import json
import threading

from flask import Flask, render_template, jsonify, request
from loguru import logger

from src.storage.database import get_connection, init_db, get_pending_search_results
from src.storage.graph_store import GraphStore

app = Flask(__name__, template_folder="templates")

# État global des tâches en cours
_task_status = {
    "searcher":  {"running": False, "message": ""},
    "scrapper":  {"running": False, "message": ""},
    "marketing": {"running": False, "message": ""},
}

_marketing_results = {}


# =====================================================================
# Helpers
# =====================================================================

def _get_sqlite_stats() -> dict:
    init_db()
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM search_results").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM search_results WHERE status='pending'").fetchone()[0]
        scraped = conn.execute("SELECT COUNT(*) FROM search_results WHERE status='scraped'").fetchone()[0]
        error = conn.execute("SELECT COUNT(*) FROM search_results WHERE status='error'").fetchone()[0]
        raw_count = conn.execute("SELECT COUNT(*) FROM raw_company").fetchone()[0]
    return {
        "total": total, "pending": pending,
        "scraped": scraped, "error": error,
        "raw_companies": raw_count,
    }


def _get_search_results(limit: int = 100) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM search_results ORDER BY score DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def _get_neo4j_graph_data() -> dict:
    """Retourne les noeuds et arêtes pour vis.js."""
    try:
        gs = GraphStore()
        nodes = []
        edges = []

        with gs.driver.session() as session:
            # Noeuds Company
            result = session.run("""
                MATCH (c:Company)
                RETURN c.name AS name, c.tier AS tier, c.website AS website,
                       c.email AS email, c.phone AS phone, c.address AS address,
                       c.source AS source, c.confidence AS confidence
            """)
            for r in result:
                tier = r["tier"]
                color = "#4CAF50" if tier == 1 else "#2196F3" if tier == 2 else "#9E9E9E"
                size = 30 if tier == 1 else 20 if tier == 2 else 15
                nodes.append({
                    "id": r["name"],
                    "label": r["name"],
                    "color": color,
                    "size": size,
                    "tier": tier,
                    "title": (
                        f"<b>{r['name']}</b><br>"
                        f"Tier: {tier or '?'}<br>"
                        f"Web: {r['website'] or '-'}<br>"
                        f"Email: {r['email'] or '-'}<br>"
                        f"Phone: {r['phone'] or '-'}<br>"
                        f"Address: {r['address'] or '-'}"
                    ),
                })

            # Noeuds Tier
            result = session.run("MATCH (t:Tier) RETURN t.level AS level, t.label AS label")
            for r in result:
                nodes.append({
                    "id": f"tier_{r['level']}",
                    "label": f"Tier {r['level']}\n{r['label'] or ''}",
                    "color": "#FF9800",
                    "size": 40,
                    "shape": "diamond",
                    "tier": None,
                    "title": f"<b>Tier {r['level']}</b><br>{r['label']}",
                })

            # Arêtes
            result = session.run("""
                MATCH (a)-[r]->(b)
                WHERE (a:Company OR a:Tier) AND (b:Company OR b:Tier)
                RETURN
                    CASE WHEN a:Tier THEN 'tier_' + toString(a.level) ELSE a.name END AS from_id,
                    CASE WHEN b:Tier THEN 'tier_' + toString(b.level) ELSE b.name END AS to_id,
                    type(r) AS rel_type,
                    r.reason AS reason
            """)
            for r in result:
                rel = r["rel_type"]
                color_map = {
                    "BELONGS_TO": "#FF9800",
                    "MENTIONS": "#9C27B0",
                    "SUPPLIES": "#F44336",
                    "POTENTIAL_SUPPLIER": "#607D8B",
                }
                edges.append({
                    "from": r["from_id"],
                    "to": r["to_id"],
                    "label": rel,
                    "color": color_map.get(rel, "#999"),
                    "dashes": rel == "POTENTIAL_SUPPLIER",
                    "title": r["reason"] or rel,
                })

        gs.close()
        return {"nodes": nodes, "edges": edges}
    except Exception as e:
        logger.error(f"Erreur Neo4j graph: {e}")
        return {"nodes": [], "edges": []}


def _get_marketing_data() -> dict:
    """Lit les données Tier 1/2 depuis Neo4j pour la page marketing."""
    try:
        gs = GraphStore()
        tier1 = gs.get_companies_by_tier(1)
        tier2 = gs.get_companies_by_tier(2)
        gs.close()
        return {"tier1": tier1, "tier2": tier2}
    except Exception as e:
        logger.error(f"Erreur marketing data: {e}")
        return {"tier1": [], "tier2": []}


# =====================================================================
# Runner async dans un thread
# =====================================================================

def _run_async_in_thread(agent_name: str, coro_func, **kwargs):
    """Lance une coroutine dans un thread séparé pour ne pas bloquer Flask."""
    def target():
        _task_status[agent_name]["running"] = True
        _task_status[agent_name]["message"] = "En cours..."
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(coro_func(**kwargs))
            _task_status[agent_name]["message"] = "Terminé"
        except Exception as e:
            _task_status[agent_name]["message"] = f"Erreur: {e}"
        finally:
            _task_status[agent_name]["running"] = False

    t = threading.Thread(target=target, daemon=True)
    t.start()


# =====================================================================
# Routes
# =====================================================================

@app.route("/")
def index():
    stats = _get_sqlite_stats()
    return render_template("index.html", stats=stats)


@app.route("/dashboard")
def dashboard():
    stats = _get_sqlite_stats()
    results = _get_search_results(200)
    return render_template("dashboard.html", stats=stats, results=results)


@app.route("/graph")
def graph():
    return render_template("graph.html")


@app.route("/marketing")
def marketing():
    data = _get_marketing_data()
    return render_template("marketing.html", data=data)


@app.route("/api/graph-data")
def api_graph_data():
    return jsonify(_get_neo4j_graph_data())


@app.route("/api/stats")
def api_stats():
    return jsonify(_get_sqlite_stats())


@app.route("/api/status")
def api_status():
    flat = {
        **_task_status,
        "marketing_running": _task_status["marketing"]["running"],
    }
    return jsonify(flat)


@app.route("/api/marketing-results")
def api_marketing_results():
    return jsonify(_marketing_results)


@app.route("/api/run/<agent_name>", methods=["POST"])
def api_run(agent_name: str):
    if _task_status.get(agent_name, {}).get("running"):
        return jsonify({"error": f"{agent_name} est déjà en cours"}), 409

    if agent_name == "searcher":
        from src.agents.target_searcher import run_pipeline
        max_q = request.json.get("max_per_query", 5) if request.json else 5
        _run_async_in_thread("searcher", run_pipeline, max_per_query=max_q)

    elif agent_name == "scrapper":
        from src.agents.scrapper_agent import main as scrapper_main
        limit = request.json.get("limit", 20) if request.json else 20
        _run_async_in_thread("scrapper", scrapper_main, limit=limit)

    elif agent_name == "marketing":
        from src.agents.marketing_agent import run_marketing

        async def _run_and_store_marketing():
            global _marketing_results
            result = await run_marketing()
            _marketing_results = result

        _run_async_in_thread("marketing", _run_and_store_marketing)

    else:
        return jsonify({"error": "Agent inconnu"}), 404

    return jsonify({"status": "started", "agent": agent_name})


# =====================================================================
# Main
# =====================================================================

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
