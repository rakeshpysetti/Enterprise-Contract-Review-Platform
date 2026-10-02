PYTHON ?= python

.PHONY: install run test lint typecheck check evaluate docker-up docker-down docker-logs docker-config

install:
	$(PYTHON) -m pip install -e ".[dev]"

run:
	$(PYTHON) -m uvicorn app.main:app --app-dir backend --reload

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff format --check backend scripts
	$(PYTHON) -m ruff check backend scripts

typecheck:
	$(PYTHON) -m mypy

check: lint typecheck test

evaluate:
	$(PYTHON) scripts/evaluate_extraction.py --output data/evaluation/results.json

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

docker-config:
	docker compose config --quiet
