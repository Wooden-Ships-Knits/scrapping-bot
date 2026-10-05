# Common tasks. Every target runs inside the uv-managed environment.
.DEFAULT_GOAL := help

.PHONY: help install fmt lint typecheck test check clean

help: ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-10s %s\n", $$1, $$2}'

install: ## Create .venv, install dependencies and git hooks
	uv sync
	uv run pre-commit install

fmt: ## Format code and apply safe lint fixes
	uv run ruff format
	uv run ruff check --fix

lint: ## Lint and check formatting
	uv run ruff check
	uv run ruff format --check

typecheck: ## Type-check with pyright
	uv run pyright

test: ## Run the offline test suite
	uv run pytest

check: lint typecheck test ## Everything CI runs

clean: ## Remove caches and build artefacts (keeps data/)
	rm -rf .pytest_cache .ruff_cache build dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
