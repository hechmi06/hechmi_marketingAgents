import asyncio
import json
import math
from urllib.parse import urlparse

import httpx
from agno.agent import Agent
from agno.models.ollama import Ollama
from loguru import logger

from src.config import settings
from src.mcp.search_client import MCPSearchClient
from src.storage.database import init_db, save_search_result, get_known_domains
from src.storage.embeddings import generate_embedding
from src.storage.graph_store import GraphStore


TIER1_QUERIES = [
    '"coffret de comptage" fabricant France',
    '"NF C 14-100" fabricant coffret electrique',
    '"coffret Enedis" fabricant OR constructeur',
    '"coffret de branchement electrique" fabricant site officiel',
    '"armoire de comptage" fabricant electrique',
    '"metering cabinet" manufacturer Europe OEM',
    '"electrical meter enclosure" manufacturer',
    '"coffret de coupure" "coffret comptage" fabricant',
    'fabricant "coffret electrique" comptage consommation',
]

TIER2_QUERIES = [
    '"faisceau electrique" "coffret" sous-traitant OR assemblage',
    '"cablage interne" coffret electrique assemblage sous-traitance',
    '"wiring harness" "meter cabinet" OR "metering enclosure" subcontractor',
    '"cable assembly" "electrical cabinet" manufacturer Europe',
    'sous-traitant cablage coffret Enedis faisceaux electriques',
    '"assemblage coffret" cablage electrique prestataire',
    '"panel wiring" subcontractor industrial harness Europe',
    'sous-traitant "faisceau electrique" Tunisie OR Maroc coffret',
    '"cable harness" subcontractor Romania OR Bulgaria "electrical cabinet"',
]
EXCLUDED_DOMAINS = {
    # Réseaux sociaux
    "linkedin.com", "facebook.com", "instagram.com",
    "youtube.com", "twitter.com", "x.com",
    # Encyclopédies / docs
    "wikipedia.org", "studylibfr.com", "scribd.com",
    # E-commerce grand public
    "amazon.com", "amazon.fr", "leroymerlin.fr",
    "cdiscount.com", "fnac.com", "darty.com",
    "manomano.fr", "domomat.com",
    # Emploi
    "indeed.com", "glassdoor.com", "welcometothejungle.com",
    # Médias / presse
    "usinenouvelle.com", "lelezard.com", "businesswire.com",
    "prnewswire.com", "lefigaro.fr", "lemonde.fr",
    # Annuaires / marketplaces / directories
    "achatmat.com", "directindustry.fr", "directindustry.com", "hellopro.fr",
    "kompass.com", "europages.fr", "societe.com",
    "manageo.fr", "verif.com",
    "exportersindia.com", "indiamart.com", "alibaba.com",
    "globalinforesearch.com", "globenewswire.com",
    # Forums / guides / blogs
    "forum-electricite.com", "guidelec.com",
    "construireenfrance.fr", "electriciteinfo.com",
    "batirmoinscher.com",
    # Assurance / hors secteur
    "assurancedommageouvrage.org",
    # Gestionnaires réseau (pas fabricants)
    "enedis.fr", "rte-france.com", "erdfdistribution.fr",
}

# ============================================================
# PROTOTYPES SEMANTIQUES
# ============================================================

PROTOTYPES = {
    "tier_1": """
    entreprise qui vend des coffrets de comptage electrique,
    des armoires electriques, des tableaux electriques, des enclosures,
    des meter cabinets, des produits finis de distribution electrique
    """,
    "tier_2": """
    entreprise qui fait du cablage electrique, des faisceaux electriques,
    du wiring harness, du cable assembly, du panel wiring,
    de l'assemblage electrique ou de l'integration industrielle
    """,
}

PROTOTYPE_EMBEDDINGS = {}


# ============================================================
# OUTILS
# ============================================================

def extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def is_valid_url(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False

    domain = extract_domain(url)
    if not domain:
        return False

    for bad in EXCLUDED_DOMAINS:
        if bad in domain:
            return False

    if url.lower().endswith((".pdf", ".jpg", ".jpeg", ".png", ".zip")):
        return False

    return True


def deduplicate(results: list[dict]) -> list[dict]:
    """
    Garde 1 resultat par domaine.
    Si doublon, on garde celui avec le snippet le plus informatif.
    """
    seen = {}
    for r in results:
        domain = r["domain"]
        if domain not in seen:
            seen[domain] = r
        else:
            if len(r.get("snippet", "")) > len(seen[domain].get("snippet", "")):
                seen[domain] = r
    return list(seen.values())


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def build_prototype_embeddings() -> None:
    global PROTOTYPE_EMBEDDINGS
    if PROTOTYPE_EMBEDDINGS:
        return

    logger.info("Generation des embeddings prototypes...")
    for label, text in PROTOTYPES.items():
        vec = generate_embedding(text.strip())
        if vec:
            PROTOTYPE_EMBEDDINGS[label] = vec

    logger.info(f"Prototypes charges : {list(PROTOTYPE_EMBEDDINGS.keys())}")


def classify_by_embedding(title: str, snippet: str) -> dict:
    text = f"{title}. {snippet}".strip()
    vec = generate_embedding(text)

    if not vec:
        return {
            "label": "unknown",
            "confidence": 0.0,
            "reason": "embedding non genere",
            "scores": {}
        }

    scores = {}
    for label, proto_vec in PROTOTYPE_EMBEDDINGS.items():
        if proto_vec:
            scores[label] = cosine_similarity(vec, proto_vec)

    if not scores:
        return {
            "label": "unknown",
            "confidence": 0.0,
            "reason": "aucun prototype disponible",
            "scores": {}
        }

    best_label = max(scores, key=scores.get)
    best_score = scores[best_label]

    return {
        "label": best_label,
        "confidence": round(best_score, 3),
        "reason": "classification par similarite semantique",
        "scores": scores
    }


classifier_agent = Agent(
    model=Ollama(id=settings.ollama_model),
    instructions=[
        "Tu classes des entreprises industrielles dans une supply chain electrique.",
        "Tu reponds uniquement avec un JSON valide.",
        "Labels possibles : tier_1, tier_2, unknown.",
        "tier_1 = fabricant ou vendeur de coffrets, armoires, tableaux electriques, meter cabinets.",
        "tier_2 = entreprise de cablage, faisceaux, wiring harness, cable assembly, integration industrielle.",
        "unknown = information insuffisante ou trop ambigue."
    ],
)


def classify_by_llm(title: str, snippet: str, domain: str = "") -> dict:
    prompt = f"""
Tu classes des entreprises dans une supply chain electrique.
Reponds UNIQUEMENT avec un JSON valide, sans texte avant ou apres.

Labels :
- tier_1 : fabricant ou vendeur de coffrets, armoires, tableaux electriques, meter cabinets
- tier_2 : sous-traitant cablage, faisceaux, wiring harness, assemblage industriel
- unknown : information insuffisante ou hors secteur

Entreprise :
Titre   : {title}
Snippet : {snippet}
Domaine : {domain}

Format attendu :
{{"label": "tier_1", "confidence": 0.85, "reason": "explication courte"}}
"""
    try:
        response = httpx.post(
            f"{settings.ollama_base_url}/api/generate",
            json={
                "model":  settings.ollama_model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
            timeout=60.0,
        )
        response.raise_for_status()
        raw = response.json().get("response", "{}")
        data = json.loads(raw)
        return {
            "label":      data.get("label", "unknown"),
            "confidence": float(data.get("confidence", 0.0)),
            "reason":     data.get("reason", "classification LLM"),
        }
    except Exception as e:
        return {"label": "unknown", "confidence": 0.0, "reason": f"erreur llm: {e}"}

def hybrid_classify(title: str, snippet: str, domain: str = "") -> dict:
    """
    1) embeddings pour preclasser
    2) LLM pour arbitrer si ambigu
    3) rejet si confiance trop basse partout
    """
    emb_result = classify_by_embedding(title, snippet)

    # Score embedding trop bas → probablement hors sujet
    if emb_result["confidence"] < 0.55:
        return {
            "label": "unknown",
            "confidence": emb_result["confidence"],
            "reason": "rejeté — score embedding trop bas",
        }

    # Confiance forte → on garde embedding directement
    if emb_result["confidence"] >= 0.72:
        return emb_result

    # Zone grise (0.55–0.72) → arbitrage LLM
    llm_result = classify_by_llm(title, snippet, domain)

    if llm_result["confidence"] >= 0.55:
        return llm_result

    # LLM non concluant → on garde l'embedding avec mention
    return {
        "label": emb_result["label"],
        "confidence": emb_result["confidence"],
        "reason": "embedding confirmé (LLM non concluant)",
    }


def label_to_tier(label: str) -> int:
    if label == "tier_1":
        return 1
    if label == "tier_2":
        return 2
    return 0


# ============================================================
# RECHERCHE VIA MCP
# ============================================================

async def search_and_collect(
    queries: list[str],
    mcp_client: MCPSearchClient,
    max_per_query: int = 10
) -> list[dict]:
    all_results = []

    for query in queries:
        logger.info(f"[MCP] search_web: {query}")
        try:
            hits = await mcp_client.search(query, max_results=max_per_query)

            for r in hits:
                title = r.get("title", "").strip()
                url = r.get("url", "").strip()
                snippet = r.get("body", "").strip()

                if not is_valid_url(url):
                    continue

                domain = extract_domain(url)

                all_results.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "domain": domain,
                    "query": query,
                })

        except Exception as e:
            logger.warning(f"Erreur MCP search_web pour '{query}': {e}")

        await asyncio.sleep(settings.request_delay_seconds)

    return all_results


# ============================================================
# PIPELINE PRINCIPAL
# ============================================================

async def run_pipeline(max_per_query: int = 10) -> list[dict]:
    logger.info("=== Target Searcher Hybride — Demarrage ===")

    init_db()
    build_prototype_embeddings()

    # 0. Charger les domaines déjà connus (SQLite + Neo4j)
    sqlite_domains = get_known_domains()
    try:
        with GraphStore() as gs:
            neo4j_domains = gs.get_known_domains()
    except Exception as e:
        logger.warning(f"Neo4j indisponible pour dédup domaines: {e}")
        neo4j_domains = set()

    already_known = sqlite_domains | neo4j_domains
    logger.info(f"Domaines déjà connus : {len(already_known)} (SQLite={len(sqlite_domains)}, Neo4j={len(neo4j_domains)})")

    # 1. collecte brute
    logger.info("Etape 1/4 — Recherche web MCP")
    async with MCPSearchClient() as client:
        tier1_raw = await search_and_collect(TIER1_QUERIES, client, max_per_query)
        tier2_raw = await search_and_collect(TIER2_QUERIES, client, max_per_query)

    all_raw = tier1_raw + tier2_raw
    logger.info(f"{len(all_raw)} resultats bruts collectes")

    # 2. dedup (intra-batch + vs base existante)
    logger.info("Etape 2/4 — Deduplication")
    deduped = deduplicate(all_raw)

    before_filter = len(deduped)
    deduped = [
        r for r in deduped
        if r["domain"].replace("www.", "") not in already_known
    ]
    skipped = before_filter - len(deduped)
    if skipped:
        logger.info(f"{skipped} domaines déjà connus ignorés")
    logger.info(f"{len(deduped)} resultats apres deduplication")

    # 3. classification hybride
    logger.info("Etape 3/4 — Classification hybride")
    final_results = []

    for r in deduped:
        classification = hybrid_classify(
            title=r["title"],
            snippet=r["snippet"],
            domain=r["domain"]
        )

        label = classification["label"]
        confidence = classification["confidence"]
        reason = classification["reason"]
        tier = label_to_tier(label)

        # on ignore les cas totalement inconnus
        if tier == 0:
            logger.debug(f"Ignored unknown: {r['domain']}")
            continue

        # score technique = confidence*100 pour compatibilite DB existante
        score = int(confidence * 100)

        save_search_result(
            url=r["url"],
            domain=r["domain"],
            title=r["title"],
            snippet=r["snippet"],
            query=r["query"],
            tier_guess=tier,
            tier_final=tier,
            score=score,
            source="mcp_ddg"
        )

        final_results.append({
            "title": r["title"],
            "url": r["url"],
            "domain": r["domain"],
            "query": r["query"],
            "label": label,
            "tier": tier,
            "confidence": confidence,
            "reason": reason,
            "score": score,
        })

        logger.info(
            f"OK | {r['domain']} | label={label} | confidence={confidence} | reason={reason}"
        )

    logger.success(f"{len(final_results)} prospects sauvegardes dans SQLite")
    return final_results


# ============================================================
# MODE INTERACTIF
# ============================================================

async def main_async():
    print("=== Target Searcher Hybride (MCP + Embeddings + LLM) ===")
    n = input("Nombre de resultats par query [5] : ").strip()
    max_per_query = int(n) if n.isdigit() else 5

    results = await run_pipeline(max_per_query=max_per_query)

    print("\n=== RESULTATS ===")
    for i, r in enumerate(results[:20], 1):
        print(
            f"{i:02d}. {r['domain']} | Tier {r['tier']} | "
            f"confidence={r['confidence']} | {r['reason']}"
        )

    print(f"\nTotal sauvegarde : {len(results)}")


if __name__ == "__main__":
    asyncio.run(main_async())