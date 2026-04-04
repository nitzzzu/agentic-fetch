import argparse
import asyncio
import json
import sys
import httpx

BASE_URL = "http://localhost:8000"


def main():
    parser = argparse.ArgumentParser(description="AI-optimized web fetch -> markdown")
    parser.add_argument("url")
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--selector", help="CSS selector to target")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--no-links", action="store_false", dest="include_links")
    parser.add_argument("--images", action="store_true", dest="include_images")
    parser.add_argument("--browser", action="store_true", dest="force_browser")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    async def run():
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(f"{BASE_URL}/fetch", json={
                "url": args.url,
                "max_tokens": args.max_tokens,
                "selector": args.selector,
                "offset": args.offset,
                "include_links": args.include_links,
                "include_images": args.include_images,
                "force_browser": args.force_browser,
            })
            r.raise_for_status()
            data = r.json()

        if args.as_json:
            print(json.dumps(data, indent=2))
            return

        print(data["markdown"])

        if data.get("truncated"):
            print(f"\n---\n*Truncated. Fetch next page with: --offset {data['next_offset']}*")

    try:
        asyncio.run(run())
    except httpx.ConnectError:
        print("Error: agentic-fetch service not running.", file=sys.stderr)
        sys.exit(1)
