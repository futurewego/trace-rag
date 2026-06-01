.PHONY: up down logs migrate migrate-rollback migrate-new dev frontend test test-unit lint fmt typecheck clean

# Infra
up:
	docker compose up -d
	@echo "Waiting for postgres..."
	@sleep 3
	@docker compose ps

down:
	docker compose down

logs:
	docker compose logs -f

# Database
migrate:
	cd rag-backend && . .venv/bin/activate && alembic upgrade head

migrate-rollback:
	cd rag-backend && . .venv/bin/activate && alembic downgrade -1

migrate-new:
	cd rag-backend && . .venv/bin/activate && alembic revision --autogenerate -m "$(MSG)"

# Dev
dev:
	cd rag-backend && . .venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8088

frontend:
	cd rag-frontend && npm run dev

# Tests
test:
	cd rag-backend && . .venv/bin/activate && pytest tests/ -x --tb=short

test-unit:
	cd rag-backend && . .venv/bin/activate && pytest tests/unit/ -x --tb=short --cov=app --cov-report=term-missing

# Quality
lint:
	cd rag-backend && . .venv/bin/activate && ruff check app/ tests/

fmt:
	cd rag-backend && . .venv/bin/activate && ruff format app/ tests/

typecheck:
	cd rag-backend && . .venv/bin/activate && mypy app/ --ignore-missing-imports

# Cleanup
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
