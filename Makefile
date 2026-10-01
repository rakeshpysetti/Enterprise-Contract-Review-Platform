PYTHON ?= python

.PHONY: install run test evaluate docker-up docker-down docker-logs docker-config

install:
	$(PYTHON) -m pip install -e ".[dev]"

run:
	$(PYTHON) -m uvicorn app.main:app --app-dir backend --reload

test:
	$(PYTHON) -m pytest

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
