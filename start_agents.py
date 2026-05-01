"""
Démarre les 3 agents A2A en parallèle (chacun sur son port).

Usage : python start_agents.py

Les agents exposent :
  - http://localhost:8001  →  target_searcher   (/.well-known/agent.json)
  - http://localhost:8002  →  scrapper_agent     (/.well-known/agent.json)
  - http://localhost:8003  →  marketing_agent    (/.well-known/agent.json)
"""

import multiprocessing
import uvicorn


def run_target():
    from src.agents.api.target_api import app
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")


def run_scrapper():
    from src.agents.api.scrapper_api import app
    uvicorn.run(app, host="0.0.0.0", port=8002, log_level="info")


def run_marketing():
    from src.agents.api.marketing_api import app
    uvicorn.run(app, host="0.0.0.0", port=8003, log_level="info")


if __name__ == "__main__":
    print("=" * 60)
    print("  Démarrage des 3 agents A2A")
    print("  target_searcher  → http://localhost:8001")
    print("  scrapper_agent   → http://localhost:8002")
    print("  marketing_agent  → http://localhost:8003")
    print("=" * 60)

    processes = [
        multiprocessing.Process(target=run_target, name="target_searcher"),
        multiprocessing.Process(target=run_scrapper, name="scrapper_agent"),
        multiprocessing.Process(target=run_marketing, name="marketing_agent"),
    ]

    for p in processes:
        p.start()
        print(f"  [OK] {p.name} démarré (PID {p.pid})")

    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        print("\nArrêt des agents...")
        for p in processes:
            p.terminate()
        print("Agents arrêtés.")
