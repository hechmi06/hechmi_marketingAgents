"""
Ajoute les relations BELONGS_TO -> Tier pour toutes les Company existantes.
Les relations MENTIONS/SUPPLIES seront créées par le scrapper_agent
lors du scraping (détection de mentions croisées).
"""
from loguru import logger
from src.storage.graph_store import GraphStore

gs = GraphStore()
gs.create_constraints()

companies = gs.get_all_companies()
logger.info(f"{len(companies)} entreprises dans Neo4j")

# Relier chaque Company à son Tier
for c in companies:
    name = c["name"]
    tier = c.get("tier")
    if tier in (1, 2):
        gs.link_company_to_tier(name, tier)
        logger.info(f"  {name} -> Tier {tier}")

# Stats
with gs.driver.session() as session:
    nodes = session.run("MATCH (n) RETURN labels(n)[0] AS label, count(n) AS n").data()
    rels = session.run("MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS n").data()

    print("\n--- Noeuds ---")
    for n in nodes:
        print(f"  {n['label']} : {n['n']}")
    print("\n--- Relations ---")
    if rels:
        for r in rels:
            print(f"  {r['type']} : {r['n']}")
    else:
        print("  (aucune relation — les MENTIONS seront créées par le scrapper)")

gs.close()
