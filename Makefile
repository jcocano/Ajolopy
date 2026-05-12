# Ajolopy harness — local task runner. Mirrors every CI check so a
# developer can validate locally before pushing.

.PHONY: help install check format lint typecheck test board hooks clean

.DEFAULT_GOAL := help

help:
	@echo "Targets:"
	@echo "  install    uv sync + pre-commit install"
	@echo "  check      lint + format-check + typecheck + test + board (mirrors CI)"
	@echo "  format     auto-format and auto-fix imports"
	@echo "  lint       ruff check"
	@echo "  typecheck  pyright"
	@echo "  test       pytest"
	@echo "  board      board.py validate"
	@echo "  hooks      pre-commit run --all-files"
	@echo "  clean      remove caches and build artifacts"

install:
	uv sync
	uv run pre-commit install

check: lint format-check typecheck test board

format:
	uv run ruff format
	uv run ruff check --fix

format-check:
	uv run ruff format --check

lint:
	uv run ruff check

typecheck:
	uv run pyright

test:
	uv run pytest

board:
	uv run python tools/board.py validate

hooks:
	uv run pre-commit run --all-files

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov dist build *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
