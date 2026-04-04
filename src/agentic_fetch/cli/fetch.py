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
    parser = argparse.ArgumentParser(description="AI-optimized web fetch -> markdown")
    parser.add_argument("url")
    parser.add_argument("--api-url", help=f"agentic-fetch service URL (saved to {CONFIG_FILE})")
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--selector", help="CSS selector to target")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--no-links", action="store_false", dest="include_links")
    parser.add_argument("--images", action="store_true", dest="include_images")
    parser.add_argument("--browser", action="store_true", dest="force_browser")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if args.api_url:
        save_api_url(args.api_url)
        base_url = args.api_url.rstrip("/")
    else:
        base_url = load_api_url()

    async def run():
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(f"{base_url}/fetch", json={
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
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return

        sys.stdout.buffer.write((data["markdown"] or "").encode("utf-8"))
        sys.stdout.buffer.write(b"\n")

        if data.get("truncated"):
            msg = f"\n---\n*Truncated. Fetch next page with: --offset {data['next_offset']}*\n"
            sys.stdout.buffer.write(msg.encode("utf-8"))

    try:
        asyncio.run(run())
    except httpx.ConnectError:
        print(f"Error: agentic-fetch service not running at {base_url}.", file=sys.stderr)
        sys.exit(1)
