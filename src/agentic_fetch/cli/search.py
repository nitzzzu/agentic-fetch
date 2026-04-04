import argparse
import asyncio
import json
import sys
import httpx

BASE_URL = "http://localhost:8000"


def main():
    parser = argparse.ArgumentParser(description="AI-optimized web search")
    parser.add_argument("query")
    parser.add_argument("--engine", choices=["auto", "google", "duckduckgo"], default="auto")
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    async def run():
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{BASE_URL}/search", json={
                "query": args.query,
                "engine": args.engine,
                "max_results": args.max_results,
            })
            r.raise_for_status()
            data = r.json()

        if args.as_json:
            print(json.dumps(data, indent=2))
            return

        print(f"# Search: {data['query']} ({data['engine_used']})\n")
        for i, res in enumerate(data["results"], 1):
            print(f"{i}. **{res['title']}**")
            print(f"   {res['url']}")
            if res["snippet"]:
                print(f"   {res['snippet']}")
            print()

    try:
        asyncio.run(run())
    except httpx.ConnectError:
        print("Error: agentic-fetch service not running. Start with: uvicorn agentic_fetch.main:app",
              file=sys.stderr)
        sys.exit(1)
