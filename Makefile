.PHONY: install test lint typecheck format check clean

install:
	uv sync --extra dev

test:
	uv run pytest

test-cov:
	uv run pytest --cov=pdf_a11y --cov-report=term-missing --cov-report=html

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

format:
	uv run ruff format src tests
	uv run ruff check --fix src tests

typecheck:
	uv run mypy src/pdf_a11y

check: lint typecheck test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage dist build
	find . -type d -name __pycache__ -exec rm -rf {} +
