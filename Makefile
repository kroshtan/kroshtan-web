.PHONY: help test
.DEFAULT_GOAL := help

VENV_DIR = ./.venv
PYTHON = $(VENV_DIR)/bin/python
PORT ?= 8000

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = "(: ).*?## "}; {sub("Makefile:", "", $$1); printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

create-venv:  ## Create the Python venv (with uv inside it) if it does not exist
	test -d $(VENV_DIR) || (python3 -m venv $(VENV_DIR) && $(VENV_DIR)/bin/pip install --upgrade pip uv)

install: create-venv  ## Install dependencies and the pre-commit hook
	$(PYTHON) -m uv sync --all-groups
	$(VENV_DIR)/bin/pre-commit install

install-ci:  ## Install dependencies in CI (uses the system uv; no venv exists yet)
	uv sync --all-groups --frozen

lock: create-venv  ## Re-resolve uv.lock after editing pyproject.toml
	$(PYTHON) -m uv lock

dev:  ## Run the site locally with auto-reload on http://localhost:$(PORT)
	$(PYTHON) -m uv run uvicorn app.main:app --reload --reload-dir app --reload-dir content --reload-dir prompts \
		--reload-include '*.yaml' --reload-include '*.md' --reload-include '*.html' --reload-include '*.css' \
		--reload-include '*.js' --port $(PORT)

fix:  ## Run pre-commit (ruff, mypy, pydoclint, whitespace) on all files
	$(VENV_DIR)/bin/pre-commit run --all-files

test:  ## Run the test suite
	$(PYTHON) -m uv run pytest

todos:  ## List every TODO placeholder left in the site content
	@grep -rn "TODO" content/ prompts/ || echo "No TODOs left in content/."

clean:  ## Remove caches, coverage output and the venv
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml htmlcov $(VENV_DIR)
	find . -name '__pycache__' -prune -exec rm -rf {} +
