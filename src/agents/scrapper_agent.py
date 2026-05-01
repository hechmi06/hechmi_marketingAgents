import asyncio
import json
import re
from urllib.parse import urljoin, urlparse

import httpx
from loguru import logger

from src.config import settings
from src.models.company import Company
from src.mcp.search_client import MCPSearchClient
from src.storage.database import (
    get_pending_search_results,
    mark_search_result,
    save_raw_company,
)
from src.storage.embeddings import generate_embedding_async
from src.storage.graph_store import GraphStore

_SUBPAGE_SLUGS = [
    "/contact", "/contact-us", "/contacts",
    "/nous-contacter", "/about", "/about-us",
    "/a-propos", "/qui-sommes-nous",
    "/mentions-legales", "/mentions-légales", "/legal",
]

PRIORITY_SLUGS = ["/contact", "/nous-contacter", "/contact-us"]

_MD_LINK_RE = re.compile(r"\[(?:[^\]]*)\]\((https?://[^)]+)\)")

# ---------------------------------------------------------------------------
# Extraction du pays
# ---------------------------------------------------------------------------

_TLD_TO_COUNTRY = {
    ".fr": "France",
    ".de": "Germany",
    ".es": "Spain",
    ".it": "Italy",
    ".be": "Belgium",
    ".nl": "Netherlands",
    ".pt": "Portugal",
    ".ch": "Switzerland",
    ".at": "Austria",
    ".pl": "Poland",
    ".ro": "Romania",
    ".bg": "Bulgaria",
    ".tn": "Tunisie",
    ".ma": "Maroc",
    ".lu": "Luxembourg",
    ".gb": "United Kingdom",
    ".uk": "United Kingdom",
}

_COUNTRY_KEYWORDS = {
    "France":          [r"\bfrance\b", r"\bfrançais\b", r"\bfrançaise\b"],
    "Germany":         [r"\bgermany\b", r"\bdeutschland\b", r"\bgmbh\b"],
    "Spain":           [r"\bspain\b", r"\bespaña\b", r"\bespañol\b"],
    "Italy":           [r"\bitaly\b", r"\bitalia\b", r"\bitaliano\b"],
    "Belgium":         [r"\bbelgique\b", r"\bbelgium\b", r"\bbelgisch\b"],
    "Romania":         [r"\bromania\b", r"\broumanie\b"],
    "Bulgaria":        [r"\bbulgaria\b", r"\bbulgarie\b"],
    "Tunisie":         [r"\btunisie\b", r"\btunisia\b", r"\btunisien\b"],
    "Maroc":           [r"\bmaroc\b", r"\bmorocco\b", r"\bmarocain\b"],
    "Netherlands":     [r"\bnetherlands\b", r"\bpays-bas\b", r"\bnederland\b"],
    "Switzerland":     [r"\bsuisse\b", r"\bswitzerland\b", r"\bschweiz\b"],
}


def _extract_country(url: str, markdown: str) -> str | None:
    """Détecte le pays depuis le TLD de l'URL, puis depuis le contenu."""
    # 1. Depuis le TLD du domaine
    try:
        host = urlparse(url).netloc.lower()
        for tld, country in _TLD_TO_COUNTRY.items():
            if host.endswith(tld) or f"{tld}/" in url.lower():
                return country
    except Exception:
        pass

    # 2. Depuis les mots clés dans le contenu
    text_lower = markdown.lower()
    for country, patterns in _COUNTRY_KEYWORDS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return country

    return None


# ---------------------------------------------------------------------------
# Sélection du meilleur email / téléphone
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(
    r"(?<!\d)"
    r"(\+?(?:33|49|44|32|34|39|351|216|212|1)[\s.\-]?(?:\d[\s.\-]?){8,11}\d"
    r"|0\d[\s.\-]?(?:\d[\s.\-]?){7,8}\d)"
    r"(?!\d)"
)

_EMAIL_PREFERRED = ["contact", "info", "commercial", "vente", "sales",
                    "direction", "accueil", "hello", "bonjour"]
_EMAIL_EXCLUDED  = ["noreply", "no-reply", "bounce", "daemon", "mailer",
                    "donotreply", "postmaster", "webmaster", "support"]


def _pick_best_email(emails: list[str]) -> str | None:
    """Choisit l'email le plus pertinent depuis une liste."""
    if not emails:
        return None

    # filtrer les emails indésirables
    cleaned = [e for e in emails
               if not any(bad in e.lower() for bad in _EMAIL_EXCLUDED)]
    if not cleaned:
        cleaned = emails

    # préférer les emails génériques de contact
    for email in cleaned:
        prefix = email.split("@")[0].lower()
        if any(p in prefix for p in _EMAIL_PREFERRED):
            return email

    return cleaned[0]


def _pick_best_phone(phones: list[str]) -> str | None:
    """Choisit le numéro le plus pertinent depuis une liste."""
    if not phones:
        return None

    # préférer les numéros avec indicatif international
    international = [p for p in phones if p.startswith("+") or p.startswith("00")]
    if international:
        return international[0]

    return phones[0]


def _extract_contacts_from_markdown(markdown: str) -> tuple[list[str], list[str]]:
    """Extrait emails et téléphones depuis un texte markdown."""
    emails = sorted(set(_EMAIL_RE.findall(markdown)))
    phones = sorted(set(_PHONE_RE.findall(markdown)))
    return emails, phones


# ---------------------------------------------------------------------------
# Détection de mentions
# ---------------------------------------------------------------------------

def _detect_mentions(
    markdown: str,
    current_name: str,
    known_names: list[str],
    min_name_length: int = 5,
) -> list[str]:
    text_lower = markdown.lower()
    mentions = []
    for name in known_names:
        if name == current_name:
            continue
        if len(name) < min_name_length:
            continue
        if re.search(rf"\b{re.escape(name.lower())}\b", text_lower):
            mentions.append(name)
    return mentions


# ---------------------------------------------------------------------------
# Matching POTENTIAL_SUPPLIER par région
# ---------------------------------------------------------------------------

def _extract_region(address: str | None) -> str | None:
    if not address:
        return None
    match = re.search(r"\b(\d{2})\d{3}\b", address)
    if match:
        return f"FR-{match.group(1)}"
    for country in ["France", "Tunisie", "Maroc", "Romania", "Bulgaria", "Germany", "Italy"]:
        if country.lower() in address.lower():
            return country
    return None


# ---------------------------------------------------------------------------
# Détection des sous-pages pertinentes
# ---------------------------------------------------------------------------

def _find_subpage_urls(base_url: str, markdown: str) -> list[str]:
    found = []
    seen = set()

    for href in _MD_LINK_RE.findall(markdown):
        path = urlparse(href).path.lower().rstrip("/")
        for slug in _SUBPAGE_SLUGS:
            if slug in path:
                normalized = href.rstrip("/")
                if normalized not in seen:
                    seen.add(normalized)
                    found.append(href)
                break

    base = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
    for slug in PRIORITY_SLUGS:
        if len(found) >= 3:
            break
        candidate = urljoin(base, slug).rstrip("/")
        if candidate not in seen:
            seen.add(candidate)
            found.append(candidate)

    return found[:3]


# ---------------------------------------------------------------------------
# Scraping multi-pages
# ---------------------------------------------------------------------------

async def _scrape_all_pages(
    client: MCPSearchClient,
    url: str,
    main_scrape: dict,
) -> tuple[str, list[str], list[str]]:
    """
    Scrape la page principale + sous-pages.
    Retourne (combined_markdown, all_emails, all_phones).
    """
    main_md = main_scrape.get("markdown", "")
    if not main_md:
        return "", [], []

    markdowns = [f"# Page principale : {url}\n\n{main_md}"]

    # Contacts depuis la page principale (MCP regex)
    all_emails = list(main_scrape.get("emails", []))
    all_phones = list(main_scrape.get("phones", []))

    subpage_urls = _find_subpage_urls(url, main_md)
    for sub_url in subpage_urls:
        try:
            page = await client.scrape(sub_url, max_chars=15000)
            if page.get("status") == "ok" and page.get("markdown"):
                sub_md = page["markdown"]
                markdowns.append(f"# Sous-page : {sub_url}\n\n{sub_md}")
                logger.debug(f"  Sous-page scrapée : {sub_url}")

                # Collecter contacts MCP depuis la sous-page
                all_emails.extend(page.get("emails", []))
                all_phones.extend(page.get("phones", []))

                # Extraction regex complémentaire depuis le markdown
                extra_emails, extra_phones = _extract_contacts_from_markdown(sub_md)
                all_emails.extend(extra_emails)
                all_phones.extend(extra_phones)

        except Exception as e:
            logger.debug(f"  Sous-page ignorée {sub_url}: {e}")

    # Déduplication
    all_emails = list(dict.fromkeys(all_emails))
    all_phones = list(dict.fromkeys(all_phones))

    combined = "\n\n---\n\n".join(markdowns)[:60000]
    return combined, all_emails, all_phones


# ---------------------------------------------------------------------------
# Extraction LLM via Ollama
# ---------------------------------------------------------------------------

_EXTRACT_PROMPT = """\
Extrais les informations suivantes depuis ce contenu web d'une entreprise.
Retourne UNIQUEMENT un objet JSON valide, sans texte avant ou après.

Format attendu (null ou [] si non trouvé) :
{{"name":"...","address":"...","linkedin":"...","description":"...","partners":[]}}

Règles :
- name : nom officiel court de l'entreprise (ex: "Depagne")
- address : rue + code postal + ville en une seule chaîne ou null
- linkedin : URL commençant par "https://www.linkedin.com/company/" ou null
- description : 1 phrase sur l'activité principale (produits, secteur) ou null
- partners : liste de noms d'autres entreprises mentionnées comme partenaires,
  clients, fournisseurs ou références. Uniquement des noms d'entreprises réelles.

Contenu :
{markdown}
"""


async def _extract_company_llm(markdown: str, title: str) -> dict:
    sections = markdown.split("---")
    focused = "\n---\n".join(s.strip()[:600] for s in sections if s.strip())[:3000]
    prompt = _EXTRACT_PROMPT.format(markdown=focused)

    try:
        async with httpx.AsyncClient(timeout=120.0) as http:
            response = await http.post(
                f"{settings.ollama_base_url}/api/generate",
                json={
                    "model":  settings.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
            )
            response.raise_for_status()
            raw_text = response.json().get("response", "")

        data = json.loads(raw_text)

        address_raw = data.get("address")
        if isinstance(address_raw, dict):
            address_raw = ", ".join(str(v) for v in address_raw.values() if v)
        elif not isinstance(address_raw, str):
            address_raw = None

        linkedin_raw = data.get("linkedin")
        if linkedin_raw and "linkedin.com/company/" not in str(linkedin_raw):
            linkedin_raw = None

        partners_raw = data.get("partners") or []
        if not isinstance(partners_raw, list):
            partners_raw = []
        partners = [p for p in partners_raw if isinstance(p, str) and len(p) >= 5]

        return {
            "name":        data.get("name") or title,
            "address":     address_raw,
            "linkedin":    linkedin_raw,
            "description": data.get("description"),
            "partners":    partners,
        }

    except json.JSONDecodeError:
        logger.warning("LLM : réponse non-JSON, fallback sur titre uniquement")
        return {"name": title, "address": None, "linkedin": None,
                "description": None, "partners": []}
    except Exception as e:
        logger.warning(f"LLM extraction échouée : {e}")
        return {"name": title, "address": None, "linkedin": None,
                "description": None, "partners": []}


# ---------------------------------------------------------------------------
# Traitement d'une entreprise
# ---------------------------------------------------------------------------

async def process_company(
    row,
    client: MCPSearchClient,
    gs: GraphStore,
    known_names: set[str],
    tier1_companies: list[dict],
    tier2_companies: list[dict],
):
    url        = row["url"]
    domain     = row["domain"]
    title      = row["title"]
    snippet    = row["snippet"]
    tier_final = row["tier_final"]
    score      = row["score"]

    logger.info(f"[{domain}] Scraping en cours...")

    # 1. Scrape principal (une seule fois)
    main_scrape = await client.scrape(url, max_chars=20000)
    if not main_scrape.get("markdown"):
        logger.warning(f"[{domain}] Aucun contenu récupéré")
        mark_search_result(url, "error")
        return

    # 2. Scrape multi-pages + collecte contacts de toutes les pages
    combined_markdown, all_emails, all_phones = await _scrape_all_pages(client, url, main_scrape)

    # Sélection des meilleurs contacts
    final_email = _pick_best_email(all_emails)
    final_phone = _pick_best_phone(all_phones)
    logger.debug(f"[{domain}] Contacts — email: {final_email} | phone: {final_phone} ({len(all_emails)} emails, {len(all_phones)} tels trouvés)")

    # 3. Extraction pays (TLD + contenu)
    country_detected = _extract_country(url, combined_markdown)
    logger.debug(f"[{domain}] Pays détecté : {country_detected}")

    # 4. Extraction LLM
    extracted = await _extract_company_llm(combined_markdown, title)
    logger.debug(f"[{domain}] Extraction LLM : {extracted}")

    # 5. Sauvegarde SQLite
    save_raw_company({
        "name":        extracted.get("name") or title,
        "phone":       final_phone or "",
        "email":       final_email or "",
        "website":     url,
        "country":     country_detected or "",
        "description": extracted.get("description") or snippet,
        "address":     extracted.get("address") or "",
        "linkedin":    extracted.get("linkedin") or "",
        "raw":         combined_markdown[:5000],
    })

    # 6. Construire l'objet Company
    company = Company(
        name=extracted.get("name") or title,
        website=url,
        tier=tier_final,
        country=country_detected,
        email=final_email,
        phone=final_phone,
        address=extracted.get("address"),
        linkedin=extracted.get("linkedin"),
        description=extracted.get("description") or snippet,
        source="scrapper_agent",
        confidence=round(score / 100, 2) if score else None,
    )

    # 7. Upsert Neo4j + relation BELONGS_TO
    gs.upsert_company(company)
    gs.link_company_to_tier(company.name, company.tier)
    known_names.add(company.name)
    logger.debug(f"[{domain}] Company upsertée (Tier {company.tier})")

    # 8. Relations — mentions + partenaires LLM
    mentions_found = _detect_mentions(combined_markdown, company.name, list(known_names))
    for mentioned in mentions_found:
        gs.create_mention_relation(company.name, mentioned)
        logger.info(f"[{domain}] MENTIONS : {company.name} → {mentioned}")

    for partner in extracted.get("partners", []):
        if partner == company.name:
            continue
        if partner in known_names:
            gs.create_mention_relation(company.name, partner)
            logger.info(f"[{domain}] MENTIONS (LLM) : {company.name} → {partner}")
        else:
            gs.upsert_discovered_company(partner, company.name)
            gs.create_mention_relation(company.name, partner)
            known_names.add(partner)
            logger.info(f"[{domain}] NOUVEAU + MENTIONS : {partner} (via {company.name})")

    # 9. POTENTIAL_SUPPLIER par région
    company_region = _extract_region(company.address)
    if company_region:
        if company.tier == 2:
            for t1 in tier1_companies:
                if _extract_region(t1.get("address")) == company_region:
                    gs.create_potential_supplier(
                        company.name, t1["name"],
                        f"même région: {company_region}"
                    )
                    logger.info(f"[{domain}] POTENTIAL_SUPPLIER : {company.name} → {t1['name']}")
        elif company.tier == 1:
            for t2 in tier2_companies:
                if _extract_region(t2.get("address")) == company_region:
                    gs.create_potential_supplier(
                        t2["name"], company.name,
                        f"même région: {company_region}"
                    )
                    logger.info(f"[{domain}] POTENTIAL_SUPPLIER : {t2['name']} → {company.name}")

    # 10. Embedding
    embed_text = f"{company.name} {company.description or ''}"
    embedding  = await generate_embedding_async(embed_text)
    if embedding:
        gs.update_embedding(company.name, embedding)
        logger.debug(f"[{domain}] Embedding stocké ({len(embedding)} dims)")

    # 11. Marquer comme traité
    mark_search_result(url, "scraped")
    logger.success(f"[{domain}] Traitement terminé")


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

async def main(limit: int = 20):
    rows = get_pending_search_results(limit=limit)
    if not rows:
        logger.info("Aucune entreprise en attente de scraping.")
        return

    logger.info(f"{len(rows)} entreprise(s) à scraper.")

    with GraphStore() as gs:
        gs.create_constraints()

        # Chargement unique avant la boucle
        known_names     = set(gs.get_company_names())
        tier1_companies = gs.get_companies_by_tier(1)
        tier2_companies = gs.get_companies_by_tier(2)

        async with MCPSearchClient() as client:
            for row in rows:
                try:
                    await process_company(
                        row, client, gs,
                        known_names,
                        tier1_companies,
                        tier2_companies,
                    )
                    # Refresh les listes après chaque entreprise ajoutée
                    tier1_companies = gs.get_companies_by_tier(1)
                    tier2_companies = gs.get_companies_by_tier(2)
                except Exception as e:
                    logger.error(f"Erreur pour {row['url']}: {e}")
                    mark_search_result(row["url"], "error")

        # Mentions bidirectionnelles → SUPPLIES confirmé
        gs.detect_and_upgrade_supplies()
        logger.success("Relations SUPPLIES détectées")


if __name__ == "__main__":
    asyncio.run(main())