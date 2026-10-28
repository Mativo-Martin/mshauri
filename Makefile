.PHONY: install lint typecheck test check run docker db-up db-down db-reset migrate seed test-unit seed
install:
	pip install -e ".[dev]"
lint:
	ruff check . && ruff format --check .
typecheck:
	mypy --strict app tests
test:
	pytest
check: lint typecheck test
run:
	uvicorn app.main:app --reload
docker:
	docker compose up --build

db-up:
	docker compose up -d --wait db

db-down:
	docker compose stop db

db-reset:
	docker compose down -v

migrate:
	alembic upgrade head

seed:
	python scripts/seed.py

test-unit:
	pytest tests/unit -q
