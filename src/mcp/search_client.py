import json
import os
import sys
from pathlib import Path

from loguru import logger
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

_TOOL_SERVER = Path(__file__).resolve().parent / "tool_server.py"


class MCPSearchClient:
    """
    Client MCP pour appeler les outils du tool_server.py via stdio.
    Usage :
        async with MCPSearchClient() as client:
            results = await client.search("query")
            page    = await client.scrape("https://example.com")
    """

    def __init__(self):
        self._stdio_ctx   = None
        self._session_ctx = None
        self._session     = None

    async def __aenter__(self):
        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(_TOOL_SERVER)],
            env={**os.environ, "PYTHONUTF8": "1"},
        )

        self._stdio_ctx = stdio_client(server_params)
        read, write = await self._stdio_ctx.__aenter__()

        self._session_ctx = ClientSession(read, write)
        self._session = await self._session_ctx.__aenter__()
        await self._session.initialize()

        return self

    async def __aexit__(self, *args):
        if self._session_ctx:
            await self._session_ctx.__aexit__(*args)
        if self._stdio_ctx:
            await self._stdio_ctx.__aexit__(*args)

    # ------------------------------------------------------------------
    # Helpers internes
    # ------------------------------------------------------------------

    def _parse_content(self, result) -> list[dict] | dict:
        """Parse le contenu brut retourné par un appel MCP."""
        items = []
        for content in result.content:
            if not hasattr(content, "text"):
                continue
            try:
                data = json.loads(content.text)
            except json.JSONDecodeError as e:
                logger.warning(f"MCP parse error: {e} | raw={content.text[:80]}")
                continue

            if isinstance(data, list):
                items.extend(data)
            elif isinstance(data, dict):
                items.append(data)

        return items

    async def _call(self, tool: str, params: dict):
        if self._session is None:
            raise RuntimeError("MCPSearchClient non initialisé — utiliser async with")
        return await self._session.call_tool(tool, params)

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    async def search(self, query: str, max_results: int = 10) -> list[dict]:
        """Appelle search_web — retourne une liste de {title, url, body}."""
        result = await self._call("search_web", {
            "query":       query,
            "max_results": max_results,
        })
        return self._parse_content(result)

    async def scrape(self, url: str, max_chars: int = 20000) -> dict:
        """Appelle scrape_url — retourne {url, status, markdown, emails, phones}."""
        result = await self._call("scrape_url", {
            "url":       url,
            "max_chars": max_chars,
        })
        items = self._parse_content(result)
        return items[0] if items else {"url": url, "status": "error", "markdown": "", "emails": [], "phones": []}

    async def extract_contacts(self, text: str) -> dict:
        """Appelle extract_contacts — retourne {emails, phones}."""
        result = await self._call("extract_contacts", {"text": text})
        items = self._parse_content(result)
        return items[0] if items else {"emails": [], "phones": []}