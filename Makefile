PYTHON ?= python

.PHONY: install run db-upgrade test lint typecheck check evaluate docker-up docker-down docker-logs docker-config docker-prod-up docker-prod-down docker-prod-config

install:
	$(PYTHON) -m pip install -e ".[dev]"

run:
	$(PYTHON) -m uvicorn app.main:app --app-dir backend --reload

db-upgrade:
	$(PYTHON) -m alembic upgrade head

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff format --check backend scripts migrations
	$(PYTHON) -m ruff check backend scripts migrations

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

docker-prod-up:
	docker compose -f docker-compose.prod.yml up --build -d --wait

docker-prod-down:
	docker compose -f docker-compose.prod.yml down

docker-prod-config:
	docker compose -f docker-compose.prod.yml config --quiet
