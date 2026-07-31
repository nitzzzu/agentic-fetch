# CLAUDE.md

## The contract

I do not read your implementation code. I review the spec, the tests, and the
interfaces — nothing else. Everything else is trusted only because it survived
the verification gauntlet below.

This means: **a task is not complete when the code looks right. It is complete
when `make verify` exits 0 and you have produced the completion report.**

If you cannot get `make verify` to pass, say so plainly and stop. A truthful
"I could not satisfy the mutation gate on module X" is a good outcome. A
silently weakened threshold is a failure of the task, regardless of the code.

---

## The gauntlet

Run everything with one command:

```
make verify
```

It must run these gates, in this order, failing fast:

| # | Gate | Command | Passing condition |
|---|------|---------|-------------------|
| 1 | Format | `uv run ruff format --check src/ scripts/` | no diff |
| 2 | Lint | `uv run ruff check src/ scripts/` | zero warnings (incl. C901 ≤ 25) |
| 3 | Types | `uv run mypy src/agentic_fetch` | strict mode, zero errors |
| 4 | Unit tests | `uv run pytest tests/ --ignore=tests/test_integration.py --ignore=tests/test_api_live.py --ignore=tests/test_acceptance.py -q` | all pass |
| 5 | Acceptance / Gherkin | `uv run pytest tests/test_acceptance.py -q --junitxml=.reports/bdd.xml` + `scripts/check_no_skips.py` | all scenarios pass, none skipped |
| 6 | Coverage | pytest `--cov=agentic_fetch --cov-branch` + `scripts/check_coverage.py` | ≥ 65% line, ≥ 50% branch |
| 7 | Mutation | `uv run mutmut run` + `scripts/check_mutation.py` | ≥ 70% mutants killed |
| 8 | Architecture | `uv run lint-imports` | no boundary violations |
| 9 | Dependencies | `uv export` + `uv run pip-audit` | no known vulns, no new deps unapproved |

Notes on scope, so nobody "discovers" slack later:

- `tests/test_integration.py` and `tests/test_api_live.py` are real-network /
  real-Chrome suites. They are deliberately outside the gauntlet (the gauntlet
  must be deterministic and offline) and are run manually.
- The mutation gate mutates the deterministic core (`markdown.py`, `cache.py`,
  `config.py`, `models.py` — see `[tool.mutmut]` in `pyproject.toml`).
  Network/browser modules are covered by gates 4–6 but not mutated.
- Gate 2's complexity ceiling (C901 ≤ 25) is a ratchet pinned at the current
  worst function. Lower it when hotspots are refactored; never raise it.

Coverage is a floor, not a goal. **Mutation score is the real signal** — it is
the gate that makes "nobody reads this code" a defensible position. Treat a
surviving mutant as a missing test, never as a tool quirk.

---

## What you may not touch

These are the things that make verification meaningful. Changing them to get
green is the one unrecoverable mistake in this repo.

Do not, without explicit approval in the conversation:

- Modify, delete, rename, or skip any existing test or scenario
- Lower a threshold (coverage, mutation, complexity, timeout, size budget)
- Add a suppression: `# noqa`, `# type: ignore`, `pytest.mark.skip`,
  `pytest.mark.xfail`, broadening a mypy override, etc.
- Weaken a type to `Any`, `object`, or an unchecked `cast()`
- Loosen a lint, mypy, mutmut, or import-linter rule
- Add, upgrade, or remove a dependency
- Change anything in `.github/workflows/`, the `Makefile` gate definitions,
  or the `scripts/check_*.py` gate scripts
- Delete an assertion to make a test pass

**If a test appears wrong, stop and tell me.** Explain what the test asserts,
what the correct behavior should be, and why. I will decide. You never get to
decide that the spec is mistaken.

If a rule genuinely blocks correct work, propose the exception with a
justification and wait. Do not apply it and mention it afterward.

---

## Writing tests

When I ask you to write tests, they are a spec, not a mirror of the code.

- Write from the requirement, not from the implementation. If you find yourself
  reading the function to decide what to assert, stop — you are describing
  behavior that exists rather than behavior that should exist.
- Assert on observable behavior through the public interface. Do not test
  private functions or assert on internal call sequences.
- Every test needs a real assertion. A test that only checks "no exception" is
  not a test unless the absence of an exception *is* the requirement.
- Cover the boundaries: empty, zero, one, many, max, malformed, duplicate,
  concurrent, and the error path for every failure mode you introduce.
- Use property-based tests (`hypothesis` — propose adding it to the dev extras
  when first needed) for anything with a non-trivial input space, invariant,
  round-trip, or ordering guarantee.
- No sleeps, no network, no wall-clock or random dependence. Mock HTTP with
  `respx`, mock the browser pool at its boundary, inject state via `tmp_path`
  caches. Flaky tests are broken tests.
- One reason to fail per test. The name states the behavior:
  `rejects_withdrawal_exceeding_balance`, not `test_withdraw_2`.

---

## Working loop

1. Restate the requirement in one or two sentences and list the acceptance
   criteria as you understand them. If anything is ambiguous, ask before
   writing code — a wrong assumption costs more here than a question.
2. Write or confirm the failing tests first. Show me they fail for the right
   reason.
3. Implement until green.
4. Run `make verify` in full. Not a subset. Not the fast path.
5. Fix and re-run until it exits 0.
6. Produce the completion report.

Do not batch several unrelated tasks into one verification run. One coherent
change, one green gauntlet.

---

## Completion report

End every task with exactly this, because it is all I read:

```
## Completion report

Requirement: <one line>

Gauntlet:   PASS (all 9 gates)
Coverage:   XX.X% line / XX.X% branch  (floor: 65% / 50%)
Mutation:   XX.X% killed, N survived   (floor: 70%)

Surviving mutants (if any):
- path/file:line — <what it mutated, why it is acceptable or what it reveals>

Public interface changes:
- <added/changed/removed signatures, endpoints, schemas, events — or "none">

Test files touched:
- <path> — <added N tests for ...>

Config / dependency changes:
- <or "none">

Assumptions I made:
- <or "none">

Needs your judgment:
- <anything I chose not to decide alone — or "nothing">
```

If any section would be dishonest, write the honest version instead. I would
rather find out here than in production.

---

## Out of scope for the gauntlet

The gates prove correctness against the spec. They prove nothing about
performance, security design, data migration safety, or whether the API is
pleasant to use. Flag anything in those categories in "Needs your judgment"
rather than assuming green means good.

---

## Project specifics

- Stack: Python 3.12 / FastAPI, managed with `uv` (`uv sync --extra dev`)
- Run a single test: `uv run pytest tests/test_api.py::TestFetchEndpoint::test_fetch_success -v`
- Architecture rules live in: `pyproject.toml` (`[tool.importlinter]`)
- Layer boundaries: `main` → (`fetch` | `search`) → `plugins` →
  (`browser` | `cache`) → (`http_client` | `markdown`) → (`config` | `models`).
  Lower layers never import higher ones. `agentic_fetch.cli` talks to the
  service over HTTP only — it must not import any server module.
- Complexity budget: cyclomatic ≤ 25 per function (ruff C901; ratchet down,
  never up)
- Domain notes:
  - Plugins return the FULL markdown; the FetchEngine caches it whole, then
    paginates. Never paginate inside a plugin — it would poison the cache
    with a truncated chunk. Plugin responses with `error` set are never cached.
  - The fetch pipeline is a 4-tier waterfall (plugin → httpx → httpx+browser →
    zendriver); each tier falls through on failure, so "an exception was
    swallowed" is often by design — check `log.debug` traces before "fixing".
  - Cache keys normalize URLs (tracking params + fragment stripped), so two
    URL spellings can share one entry. Synthesis entries (`/cache/write`)
    never expire and are never pruned.
  - `count_code_blocks` counts fence markers, not blocks: a closing fence
    counts as language "unknown" (pinned in `tests/test_markdown.py`).
  - Live-network suites: `uv run pytest tests/test_integration.py -v` (needs
    internet + Chrome), `tests/test_api_live.py` (needs a running service).

---

## Service reference

### Commands

```bash
uv sync --extra dev                                           # install
uv run uvicorn agentic_fetch.main:app --reload --port 8000    # dev server
make verify                                                   # the gauntlet
uv tool install .                                             # install CLI tools
docker compose up -d                                          # container
```

### Architecture

The service exposes a FastAPI HTTP API (`/search`, `/fetch`, `/fetch/batch`,
`/fetch/lines`, `/grep`, `/cache/{search,write,evict,prune,index,log,health}`,
`/health`) consumed by Claude Code skills via CLI wrappers (`agentic-search`,
`agentic-fetch`).

- **FetchEngine** (`fetch.py`) — 4-tier waterfall: plugin fast-path, httpx +
  readability, httpx-HTML rendered in the browser via `data:` URL, zendriver
  (full Chromium) when JS is required.
- **SearchEngine** (`search.py`) — routes to `google`, `duckduckgo`, `reddit`,
  `github`, `hackernews`, `cache` (BM25 over cached docs), or `auto`.
- **BrowserPool** (`browser.py`) — one zendriver Chromium instance behind a
  semaphore (default 3 tabs), with crash-recovery relaunch.
- **FetchCache** (`cache.py`) — file cache keyed by normalized URL; TTL, ETag
  revalidation, line-range/grep reads, BM25 search, prune/health maintenance.
- **MarkdownExtractor** (`markdown.py`) — readability-lxml → html-to-markdown
  with token-aware pagination.
- **SiteConfig** (`config.py`) — per-domain `config.yaml`: `strip_selectors`,
  `strip_lines` (regex), `init_scripts`, `proxy_url`.

### Plugin system

Plugins live in `src/agentic_fetch/plugins/`, auto-discovered at startup.
Extend `FetchPlugin` (`plugins/base.py`), declare `name` and `domains`
(fnmatch patterns), return `None` to fall through to the next tier. Built-in:
`reddit`, `medium` (via Freedium), `github`, `hackernews`, `wikipedia`,
`gog_games`.

### Configuration

Copy `.env.example` to `.env`. Env vars use the `AF_` prefix: `AF_PORT`,
`AF_HEADLESS`, `AF_CACHE_TTL` (0 disables), `AF_MAX_BROWSER_TABS`,
`AF_BROWSER_TIMEOUT`, `AF_HTTPX_TIMEOUT`, `GITHUB_TOKEN`/`AF_GITHUB_TOKEN`.
