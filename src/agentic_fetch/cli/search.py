import argparse
import asyncio
import json
import sys
from pathlib import Path
import httpx

CONFIG_FILE = Path.home() / ".agentic-fetch"
DEFAULT_URL = "http://localhost:8000"


def load_api_url() -> str:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            return data.get("api_url", DEFAULT_URL).rstrip("/")
        except Exception:
            pass
    return DEFAULT_URL


def save_api_url(url: str):
    data = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    data["api_url"] = url.rstrip("/")
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


def main():
    parser = argparse.ArgumentParser(description="AI-optimized web search")
    parser.add_argument("query")
    parser.add_argument("--api-url", help=f"agentic-fetch service URL (saved to {CONFIG_FILE})")
    parser.add_argument("--engine", choices=["auto", "google", "duckduckgo"], default="google")
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if args.api_url:
        save_api_url(args.api_url)
        base_url = args.api_url.rstrip("/")
    else:
        base_url = load_api_url()

    async def run():
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{base_url}/search", json={
                "query": args.query,
                "engine": args.engine,
                "max_results": args.max_results,
            })
            r.raise_for_status()
            data = r.json()

        if args.as_json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
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
        print(f"Error: agentic-fetch service not running at {base_url}.", file=sys.stderr)
        sys.exit(1)
