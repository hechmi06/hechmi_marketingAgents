import json
import httpx
from loguru import logger
from src.config import settings
from src.storage.graph_store import GraphStore


# ============================================================
# PROMPTS
# ============================================================

_TIER1_PROMPT = """\
Tu es un expert en stratégie commerciale B2B industrielle.
Voici une liste d'entreprises fabricants de coffrets électriques (Tier 1).
SBT est une entreprise tunisienne spécialisée dans le câblage électrique
et les faisceaux. Elle cherche à devenir sous-traitant de ces fabricants.

Entreprises Tier 1 :
{companies}

Analyse chaque entreprise et retourne UNIQUEMENT un JSON valide :
{{
  "top_prospects": [
    {{
      "name": "...",
      "priority": "haute|moyenne|faible",
      "reason": "pourquoi SBT devrait les contacter",
      "contact_angle": "comment approcher cette entreprise"
    }}
  ],
  "summary": "résumé en 2 phrases"
}}

Critères de priorité :
- haute : grande entreprise, forte activité coffrets, présence internationale
- moyenne : entreprise moyenne, activité coffrets confirmée
- faible : petite entreprise ou activité incertaine
"""

_TIER2_PROMPT = """\
Tu es un expert en stratégie commerciale B2B industrielle.
Voici une liste d'entreprises intermédiaires (Tier 2) — assembleurs et
intégrateurs qui travaillent avec des fabricants de coffrets électriques.
SBT cherche à collaborer avec eux comme sous-traitant câblage.

Entreprises Tier 2 :
{companies}

Analyse chaque entreprise et retourne UNIQUEMENT un JSON valide :
{{
  "top_prospects": [
    {{
      "name": "...",
      "priority": "haute|moyenne|faible",
      "reason": "pourquoi SBT devrait les contacter",
      "contact_angle": "comment approcher cette entreprise"
    }}
  ],
  "summary": "résumé en 2 phrases"
}}
"""

_PITCH_PROMPT = """\
Tu es un expert en prospection B2B industrielle.
SBT est une entreprise tunisienne spécialisée dans :
- Le câblage électrique industriel
- Les faisceaux électriques
- L'assemblage de coffrets de comptage
- La sous-traitance pour fabricants européens

Avantages compétitifs de SBT :
- Coûts de production 40-50% inférieurs à l'Europe
- Proximité géographique (Tunisie → France en 2h d'avion)
- Équipes qualifiées, normes européennes respectées
- Flexibilité et réactivité sur les volumes

Voici une entreprise prospect :
Nom : {name}
Activité : {description}
Adresse : {address}
Email : {email}
Tier : {tier}

Génère un pitch commercial personnalisé et retourne UNIQUEMENT un JSON valide :
{{
  "subject": "objet d'email accrocheur et personnalisé (max 10 mots)",
  "pitch_email": "email de prospection complet (3-4 paragraphes, professionnel, personnalisé à cette entreprise)",
  "pitch_linkedin": "message LinkedIn court (3-4 phrases max, direct et engageant)",
  "key_argument": "l'argument principal adapté à cette entreprise spécifique",
  "follow_up": "suggestion de relance si pas de réponse"
}}

Règles :
- Personnalise chaque pitch avec le nom et l'activité de l'entreprise
- Mentionne un besoin concret que SBT peut combler pour cette entreprise
- Sois professionnel mais pas trop formel
- Écris en français
"""

_TARGETING_PROMPT = """\
Tu es un expert en développement commercial industriel.
SBT est une entreprise tunisienne de câblage électrique cherchant
des clients en Europe (France principalement).

Voici les meilleurs prospects identifiés :

Tier 1 (fabricants coffrets) :
{tier1_prospects}

Tier 2 (assembleurs/intégrateurs) :
{tier2_prospects}

Génère un plan de ciblage et retourne UNIQUEMENT un JSON valide :
{{
  "priorité_1": {{
    "entreprises": ["nom1", "nom2"],
    "action": "action concrète à faire",
    "message_cle": "argument commercial principal"
  }},
  "priorité_2": {{
    "entreprises": ["nom3", "nom4"],
    "action": "action concrète à faire",
    "message_cle": "argument commercial principal"
  }},
  "priorité_3": {{
    "entreprises": ["nom5", "nom6"],
    "action": "action concrète à faire",
    "message_cle": "argument commercial principal"
  }},
  "conseil_global": "conseil stratégique en 2 phrases pour SBT"
}}
"""


# ============================================================
# APPEL LLM
# ============================================================

async def _call_llm(prompt: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={
                    "model":  settings.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
            )
            response.raise_for_status()
            raw = response.json().get("response", "{}")
            return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LLM réponse non-JSON")
        return {}
    except Exception as e:
        logger.error(f"Erreur LLM : {e}")
        return {}


# ============================================================
# FORMATAGE DES DONNÉES
# ============================================================

def _format_companies(companies: list[dict]) -> str:
    lines = []
    for c in companies:
        line = f"- {c.get('name', 'N/A')}"
        if c.get('email'):
            line += f" | email: {c['email']}"
        if c.get('address'):
            line += f" | adresse: {c['address']}"
        if c.get('confidence'):
            line += f" | score: {c['confidence']}"
        lines.append(line)
    return "\n".join(lines) if lines else "Aucune entreprise disponible"


# ============================================================
# PIPELINE MARKETING
# ============================================================

async def run_marketing() -> dict:
    logger.info("=== Marketing Agent — Démarrage ===")

    with GraphStore() as gs:
        tier1 = gs.get_companies_by_tier(1)
        tier2 = gs.get_companies_by_tier(2)

    logger.info(f"Tier 1 : {len(tier1)} entreprises | Tier 2 : {len(tier2)} entreprises")

    if not tier1 and not tier2:
        logger.warning("Aucune entreprise en base — pipeline marketing vide")
        return {
            "tier1_analysis":   {},
            "tier2_analysis":   {},
            "targeting_plan":   {},
            "tier1_companies":  [],
            "tier2_companies":  [],
        }

    # 1. Analyse Tier 1
    logger.info("Étape 1/3 — Analyse Tier 1")
    tier1_analysis = {}
    if tier1:
        prompt_t1 = _TIER1_PROMPT.format(
            companies=_format_companies(tier1)
        )
        tier1_analysis = await _call_llm(prompt_t1)
        logger.info(f"Tier 1 analysé — {len(tier1_analysis.get('top_prospects', []))} prospects")

    # 2. Analyse Tier 2
    logger.info("Étape 2/3 — Analyse Tier 2")
    tier2_analysis = {}
    if tier2:
        prompt_t2 = _TIER2_PROMPT.format(
            companies=_format_companies(tier2)
        )
        tier2_analysis = await _call_llm(prompt_t2)
        logger.info(f"Tier 2 analysé — {len(tier2_analysis.get('top_prospects', []))} prospects")

    # 3. Plan de ciblage global
    logger.info("Étape 3/3 — Plan de ciblage")
    tier1_top = json.dumps(
        tier1_analysis.get("top_prospects", [])[:5],
        ensure_ascii=False
    )
    tier2_top = json.dumps(
        tier2_analysis.get("top_prospects", [])[:5],
        ensure_ascii=False
    )

    targeting_plan = {}
    if tier1_top or tier2_top:
        prompt_target = _TARGETING_PROMPT.format(
            tier1_prospects=tier1_top,
            tier2_prospects=tier2_top,
        )
        targeting_plan = await _call_llm(prompt_target)

    # 4. Pitchs personnalisés pour les prospects prioritaires
    logger.info("Étape 4/4 — Génération des pitchs personnalisés")
    pitches = []
    all_prospects = []
    for p in tier1_analysis.get("top_prospects", []):
        if p.get("priority") in ("haute", "moyenne"):
            all_prospects.append((p, 1))
    for p in tier2_analysis.get("top_prospects", []):
        if p.get("priority") in ("haute", "moyenne"):
            all_prospects.append((p, 2))

    all_companies = {c["name"]: c for c in tier1 + tier2}

    for prospect, tier in all_prospects[:8]:
        name = prospect.get("name", "")
        company_data = all_companies.get(name, {})
        prompt_pitch = _PITCH_PROMPT.format(
            name=name,
            description=company_data.get("description") or prospect.get("reason", "N/A"),
            address=company_data.get("address", "N/A"),
            email=company_data.get("email", "N/A"),
            tier=tier,
        )
        pitch_result = await _call_llm(prompt_pitch)
        if pitch_result:
            pitch_result["company"] = name
            pitch_result["tier"] = tier
            pitch_result["priority"] = prospect.get("priority")
            pitches.append(pitch_result)
            logger.info(f"Pitch généré pour {name}")

    logger.info(f"{len(pitches)} pitchs générés")

    insights = {
        "tier1_analysis":  tier1_analysis,
        "tier2_analysis":  tier2_analysis,
        "targeting_plan":  targeting_plan,
        "pitches":         pitches,
        "tier1_companies": tier1,
        "tier2_companies": tier2,
    }

    logger.success("Marketing Agent terminé")
    return insights


# ============================================================
# MODE INTERACTIF
# ============================================================

async def main():
    import asyncio
    insights = await run_marketing()

    print("\n=== TIER 1 — TOP PROSPECTS ===")
    for p in insights.get("tier1_analysis", {}).get("top_prospects", []):
        print(f"  [{p.get('priority','?').upper()}] {p.get('name')}")
        print(f"    → {p.get('reason')}")
        print(f"    → Approche : {p.get('contact_angle')}")

    print("\n=== TIER 2 — TOP PROSPECTS ===")
    for p in insights.get("tier2_analysis", {}).get("top_prospects", []):
        print(f"  [{p.get('priority','?').upper()}] {p.get('name')}")
        print(f"    → {p.get('reason')}")

    print("\n=== PLAN DE CIBLAGE ===")
    plan = insights.get("targeting_plan", {})
    for key in ["priorité_1", "priorité_2", "priorité_3"]:
        if key in plan:
            p = plan[key]
            print(f"\n  {key.upper()} : {p.get('entreprises')}")
            print(f"    Action       : {p.get('action')}")
            print(f"    Message clé  : {p.get('message_cle')}")

    if plan.get("conseil_global"):
        print(f"\n  Conseil global : {plan['conseil_global']}")

    print("\n=== PITCHS PERSONNALISÉS ===")
    for pitch in insights.get("pitches", []):
        print(f"\n{'='*60}")
        print(f"  Entreprise : {pitch.get('company')} (Tier {pitch.get('tier')}) — {pitch.get('priority','?').upper()}")
        print(f"  Objet email : {pitch.get('subject')}")
        print(f"  Argument clé : {pitch.get('key_argument')}")
        print(f"\n  --- Email ---")
        print(f"  {pitch.get('pitch_email', '').replace(chr(10), chr(10) + '  ')}")
        print(f"\n  --- LinkedIn ---")
        print(f"  {pitch.get('pitch_linkedin')}")
        print(f"\n  --- Relance ---")
        print(f"  {pitch.get('follow_up')}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())