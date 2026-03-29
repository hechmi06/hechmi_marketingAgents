import asyncio
from src.mcp.search_client import MCPSearchClient

async def test():
    async with MCPSearchClient() as client:
        results = await client.search("fabricant coffret electrique france", 5)
        print("\nRESULTATS :\n")
        for r in results:
            print("TITLE :", r.get("title"))
            print("URL   :", r.get("url"))
            print("TEXT  :", r.get("body"))
            print("-" * 40)

asyncio.run(test())