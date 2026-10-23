.PHONY: install lint typecheck test check run docker
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
