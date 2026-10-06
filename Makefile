# Common tasks. Python runs in the uv environment; the web app uses pnpm in web/.
.DEFAULT_GOAL := help

.PHONY: help install fmt lint typecheck test check web-build web-check api-types e2e serve dev clean

help: ## Show this help
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-11s %s\n", $$1, $$2}'

install: ## Install Python and web dependencies, the Camoufox browser, browsers for e2e, and git hooks
	uv sync --all-extras
	uv run camoufox fetch
	pnpm --dir web install
	pnpm --dir web exec playwright install chromium
	uv run pre-commit install

fmt: ## Format code and apply safe lint fixes
	uv run ruff format
	uv run ruff check --fix

lint: ## Lint and check formatting
	uv run ruff check
	uv run ruff format --check

typecheck: ## Type-check Python with pyright
	uv run pyright

test: ## Run the offline Python test suite
	uv run pytest

api-types: ## Regenerate the web app's TypeScript types from the API
	pnpm --dir web gen:api

web-check: ## Type-check and unit-test the web app
	pnpm --dir web typecheck
	pnpm --dir web test

web-build: ## Build the web app into web/dist (served by `make serve`)
	pnpm --dir web build

e2e: web-build ## End-to-end tests in a real browser, offline
	pnpm --dir web e2e

check: lint typecheck test web-check ## Everything CI runs except e2e

serve: web-build ## Start the interface at http://127.0.0.1:8765
	uv run scrapebot serve --open

dev: ## Develop the interface: API on :8765 and Vite with hot reload on :5173
	@trap 'kill 0' INT TERM; \
	uv run scrapebot serve & \
	pnpm --dir web dev; \
	wait

clean: ## Remove caches and build artefacts (keeps data/)
	rm -rf .pytest_cache .ruff_cache build dist web/dist web/test-results web/playwright-report
	find . -name __pycache__ -type d -prune -not -path "./web/node_modules/*" -exec rm -rf {} +
