API_DIR=apps/api

.PHONY: install migrate test run seed cycle smoke

install:
	uv sync --project $(API_DIR) --extra test

migrate:
	cd $(API_DIR) && uv run --project . alembic upgrade head

test:
	cd $(API_DIR) && uv run --project . pytest -q

run:
	cd $(API_DIR) && uv run --project . uvicorn app.main:app --reload --port 8000

seed:
	cd $(API_DIR) && uv run --project . python -m app.seed

cycle:
	cd $(API_DIR) && uv run --project . python -m app.cli cycle

smoke:
	cd $(API_DIR) && uv run --project . python -m app.cli smoke
