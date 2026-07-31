.PHONY: verify format lint types unit bdd coverage mutation arch audit clean-reports

# Thresholds — changing these requires explicit approval (see CLAUDE.md).
COVERAGE_LINE_MIN   := 65
COVERAGE_BRANCH_MIN := 50
MUTATION_MIN        := 70

# Deterministic test scope: the two live-network suites are excluded from the
# gauntlet (they need real internet / Chrome and auto-skip or fail without it).
OFFLINE_IGNORES := --ignore=tests/test_integration.py --ignore=tests/test_api_live.py

REPORTS := .reports

verify: clean-reports format lint types unit bdd coverage mutation arch audit
	@echo ""
	@echo "verify: all 9 gates passed"

clean-reports:
	@mkdir -p $(REPORTS)

format:
	@echo "[1/9] format"
	uv run ruff format --check src/ scripts/

lint:
	@echo "[2/9] lint"
	uv run ruff check src/ scripts/

types:
	@echo "[3/9] types (mypy --strict)"
	uv run mypy src/agentic_fetch

unit:
	@echo "[4/9] unit tests"
	uv run pytest tests/ $(OFFLINE_IGNORES) --ignore=tests/test_acceptance.py -q

bdd:
	@echo "[5/9] acceptance scenarios (Gherkin)"
	uv run pytest tests/test_acceptance.py -q --junitxml=$(REPORTS)/bdd.xml
	uv run python scripts/check_no_skips.py $(REPORTS)/bdd.xml

coverage:
	@echo "[6/9] coverage"
	uv run pytest tests/ $(OFFLINE_IGNORES) -q \
		--cov=agentic_fetch --cov-branch \
		--cov-report=json:$(REPORTS)/coverage.json --cov-report=term
	uv run python scripts/check_coverage.py $(REPORTS)/coverage.json \
		$(COVERAGE_LINE_MIN) $(COVERAGE_BRANCH_MIN)

mutation:
	@echo "[7/9] mutation testing (mutmut)"
	uv run mutmut run
	uv run mutmut export-cicd-stats
	uv run python scripts/check_mutation.py mutants/mutmut-cicd-stats.json $(MUTATION_MIN)

arch:
	@echo "[8/9] architecture (import-linter)"
	uv run lint-imports

audit:
	@echo "[9/9] dependency audit (pip-audit)"
	uv export --format requirements.txt --no-emit-project --all-extras \
		-o $(REPORTS)/requirements-audit.txt -q
	uv run pip-audit -r $(REPORTS)/requirements-audit.txt --disable-pip
