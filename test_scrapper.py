"""
Test isolé du scrapper agent sur une URL fixe.
Lance directement sans passer par SQLite.
"""
import asyncio
from loguru import logger
from src.mcp.search_client import MCPSearchClient
from src.agents.scrapper_agent import _scrape_all_pages, _extract_company_llm

TEST_URL = "https://www.depagne.fr"
TEST_TITLE = "Depagne - Coffrets de comptage"

async def main():
    logger.info(f"=== Test scrapper sur : {TEST_URL} ===")

    async with MCPSearchClient() as client:
        # Étape 1 : scraping multi-pages
        logger.info("1. Scraping des pages...")
        markdown = await _scrape_all_pages(client, TEST_URL)

        if not markdown:
            logger.error("Aucun contenu récupéré — vérifier que Crawl4AI fonctionne")
            return

        logger.success(f"   {len(markdown)} caractères récupérés")
        print("\n--- Début markdown (500 chars) ---")
        print(markdown[:500])
        print("---\n")

        # Étape 2 : extraction LLM
        logger.info("2. Extraction LLM via Ollama...")
        extracted = await _extract_company_llm(markdown, TEST_TITLE)

        print("\n--- Données extraites (LLM) ---")
        for k, v in extracted.items():
            print(f"  {k:12s} : {v}")
        print("---\n")

        # Étape 3 : emails/phones via regex MCP
        logger.info("3. Contacts regex (MCP)...")
        main = await client.scrape(TEST_URL, max_chars=20000)
        emails = main.get("emails", [])
        phones = main.get("phones", [])
        print(f"  emails : {emails}")
        print(f"  phones : {phones}\n")

        if extracted.get("name") and extracted.get("name") != TEST_TITLE:
            logger.success(f"Nom extrait : {extracted['name']}")
        if emails or phones:
            logger.success(f"Contact(s) regex trouvé(s)")
        else:
            logger.warning("Aucun contact regex trouvé")

asyncio.run(main())
