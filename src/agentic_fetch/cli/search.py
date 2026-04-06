import argparse
import asyncio
import json
import sys
from pathlib import Path
import httpx

# Reconfigure stdout to UTF-8 so unicode in titles/snippets never crashes on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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
    parser = argparse.ArgumentParser(
        description="AI-optimized web search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Engine-specific filters:
  Google     : --date-preset, --date-from/--date-to
  Reddit     : --sort (relevance|hot|top|new|comments), --time-filter (hour|day|week|month|year|all)
  GitHub     : --sort (stars|forks|updated), --language, --search-type (repositories|code),
               --date-from/--date-to, --period (daily|weekly|monthly) for trending
  HackerNews : --story-type (story|comment), --min-points, --min-comments,
               --date-from/--date-to

GitHub token (for higher rate limits): set GITHUB_TOKEN or AF_GITHUB_TOKEN env var.

Examples:
  search "agentic AI" --engine reddit --sort top --time-filter week
  search "trending" --engine github --language python --period weekly
  search "vector database" --engine github --sort stars --date-from 2025-01-01
  search "LLM fine-tuning" --engine hackernews --min-points 50 --min-comments 10
  search "Claude API" --engine google --date-preset past_month
  search "RAG" --engine google --date-from 2025-06-01 --date-to 2026-01-01
""",
    )
    parser.add_argument("query")
    parser.add_argument("--api-url", help=f"agentic-fetch service URL (saved to {CONFIG_FILE})")
    parser.add_argument(
        "--engine",
        choices=["auto", "google", "duckduckgo", "reddit", "github", "hackernews"],
        default="auto",
    )
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--json", action="store_true", dest="as_json")

    # Date filters
    date_group = parser.add_argument_group("Date filters (Google, GitHub, HackerNews)")
    date_group.add_argument("--date-from", metavar="YYYY-MM-DD", dest="date_from",
                            help="Results published after this date")
    date_group.add_argument("--date-to", metavar="YYYY-MM-DD", dest="date_to",
                            help="Results published before this date")
    date_group.add_argument(
        "--date-preset",
        dest="date_preset",
        choices=["past_hour", "past_day", "past_week", "past_month", "past_year"],
        help="Quick date preset for Google (overrides --date-from/--date-to)",
    )

    # Reddit filters
    reddit_group = parser.add_argument_group("Reddit filters (--engine reddit)")
    reddit_group.add_argument(
        "--sort",
        choices=["relevance", "hot", "top", "new", "comments", "stars", "forks", "updated"],
        help="Sort order. Reddit: relevance|hot|top|new|comments. GitHub repos: stars|forks|updated",
    )
    reddit_group.add_argument(
        "--time-filter",
        dest="time_filter",
        choices=["hour", "day", "week", "month", "year", "all"],
        help="Reddit time window (default: all)",
    )

    # GitHub filters
    github_group = parser.add_argument_group("GitHub filters (--engine github)")
    github_group.add_argument(
        "--search-type",
        dest="search_type",
        choices=["repositories", "code"],
        help="GitHub search scope (default: repositories). Use 'code' to search code.",
    )
    github_group.add_argument("--language", help="Filter by programming language")
    github_group.add_argument(
        "--period",
        choices=["daily", "weekly", "monthly"],
        help="Trending period (default: daily). Used when query is empty or 'trending'.",
    )

    # HackerNews filters
    hn_group = parser.add_argument_group("HackerNews filters (--engine hackernews)")
    hn_group.add_argument("--min-points", type=int, dest="min_points",
                          help="Minimum points threshold")
    hn_group.add_argument("--min-comments", type=int, dest="min_comments",
                          help="Minimum comments threshold")
    hn_group.add_argument(
        "--story-type",
        dest="story_type",
        choices=["story", "comment"],
        help="HackerNews item type (default: story)",
    )

    args = parser.parse_args()

    if args.api_url:
        save_api_url(args.api_url)
        base_url = args.api_url.rstrip("/")
    else:
        base_url = load_api_url()

    async def run():
        # Build payload, omitting None values for a clean request
        payload = {
            "query": args.query,
            "engine": args.engine,
            "max_results": args.max_results,
        }
        optional = {
            "date_from": args.date_from,
            "date_to": args.date_to,
            "date_preset": args.date_preset,
            "sort": args.sort,
            "time_filter": args.time_filter,
            "search_type": args.search_type,
            "language": args.language,
            "period": args.period,
            "min_points": args.min_points,
            "min_comments": args.min_comments,
            "story_type": args.story_type,
        }
        payload.update({k: v for k, v in optional.items() if v is not None})

        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{base_url}/search", json=payload)
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
                for line in res["snippet"].splitlines():
                    print(f"   {line}")
            print()

    try:
        asyncio.run(run())
    except httpx.ConnectError:
        print(f"Error: agentic-fetch service not running at {base_url}.", file=sys.stderr)
        sys.exit(1)
