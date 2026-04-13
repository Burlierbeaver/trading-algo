.PHONY: install dev test lint run up down fmt

install:
	python3 -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -e ".[dev]"

test:
	.venv/bin/pytest -q

run:
	.venv/bin/uvicorn monitor.main:app --reload --host 0.0.0.0 --port 8787

up:
	docker compose up -d

down:
	docker compose down

seed:
	.venv/bin/python -m monitor.seed
