.PHONY: install dev test test-unit test-integration lint typecheck clean docker-up docker-down pre-commit-install

install:
	pip install -e ".[dev]"

dev:
	python main.py

test:
	pytest tests/ -v

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

typecheck:
	mypy incident_commander api

pre-commit-install:
	pre-commit install

pre-commit-run:
	pre-commit run --all-files

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage

docker-up:
	docker-compose up --build -d

docker-down:
	docker-compose down -v
