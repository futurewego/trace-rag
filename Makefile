.PHONY: up down logs migrate dev worker beat test lint fmt typecheck clean

# 基础设施
up:
	docker-compose up -d
	@echo "等待服务就绪..."
	@sleep 3
	@docker-compose ps

down:
	docker-compose down

logs:
	docker-compose logs -f

# 数据库
migrate:
	cd rag-backend && alembic upgrade head

migrate-rollback:
	cd rag-backend && alembic downgrade -1

migrate-new:
	cd rag-backend && alembic revision --autogenerate -m "$(MSG)"

# 开发服务
dev:
	cd rag-backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	cd rag-backend && celery -A app.workers.celery_app worker -l info -Q ingestion,default -c 4

beat:
	cd rag-backend && celery -A app.workers.celery_app beat -l info

# 前端
frontend:
	cd rag-frontend && npm run dev

# 测试
test:
	cd rag-backend && pytest tests/ -x --tb=short

test-unit:
	cd rag-backend && pytest tests/unit/ -x --tb=short --cov=app --cov-report=term-missing

test-integration:
	cd rag-backend && pytest tests/integration/ -x --tb=short

test-e2e:
	cd rag-backend && pytest tests/e2e/ -x --tb=short

# 代码质量
lint:
	cd rag-backend && ruff check app/ tests/

fmt:
	cd rag-backend && ruff format app/ tests/

typecheck:
	cd rag-backend && mypy app/ --ignore-missing-imports

# 清理
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
