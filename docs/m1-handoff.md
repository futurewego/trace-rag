# M1 Handoff

> Date: 2026-06-01
> Status: **M1 code complete, awaiting E2E with real API keys**

## What's done (Tasks 1-22 of 24)

### Day 1 — Infra & inventory
- ✅ docker-compose: single `pgvector/pgvector:pg16` (host port **5435**, avoid collision)
- ✅ pyproject.toml slimmed: dropped celery/qdrant/redis/torch/minio/transformers/unstructured, added psycopg/pgvector/pypdf
- ✅ venv at `rag-backend/.venv` with 30+ packages installed
- ✅ `.env.example` / `.env` / `.gitignore` / `uploads/.gitkeep`
- ✅ Code inventory at `docs/m1-code-inventory.md`
- ✅ Alembic 002 schema: documents / chunks (Vector(1536)) / sessions / messages / retrieval_logs + HNSW index

### Day 2 — Backend skeleton
- ✅ `app/config.py` slim Settings (DB + OpenAI + Anthropic + upload + retrieval params)
- ✅ `app/dependencies.py` sync DB session
- ✅ 5 models with SA 2.0 `Mapped[]` + `TYPE_CHECKING` to avoid circular imports
- ✅ `app/main.py` + `app/api/router.py`
- ✅ Sync health endpoint (rewrite — original used non-existent get_redis/get_qdrant_client)
- ✅ `POST/GET /documents`, `POST /chat` endpoints
- ✅ `Citation` schema extracted to `app/schemas/citation.py` (avoids circular import in chat.py)

### Day 3 — Document pipeline
- ✅ `parser_service.py` — pypdf page-level extraction
- ✅ `chunker_service.py` — tiktoken cl100k token-aware chunking (3 unit tests)
- ✅ `embedding_service.py` — OpenAI batch sync, lazy client
- ✅ `ingestion_service.py` — parse→chunk→embed→pgvector, 3-phase status

### Day 4 — Retrieval & generation
- ✅ `retrieval_service.py` — pgvector cosine top-k with JOIN documents
- ✅ `citation_utils.py` — regex `[N]` extractor with dedup-preserving-order (4 unit tests)
- ✅ `generation_service.py` — Claude with citation-enforcing system prompt, lazy client
- ✅ `chat.py` — full e2e with `RetrievalLog` + latency tracking

### Day 5 — Frontend
- ✅ Next.js 14 minimal skeleton (TypeScript, no Tailwind, ~250 lines total)
- ✅ `app/page.tsx` — chat UI with citations rendering
- ✅ `app/documents/page.tsx` — upload + poll list with status badges
- ✅ Build verified: `npm run build` produces 3 static routes

### Verified
- ✅ All unit tests pass: **7/7** (`pytest tests/unit/ -q`)
- ✅ Backend boots: `python -c "from app.main import app"`
- ✅ Frontend builds: `npm run build`
- ✅ DB migration applied: 5 tables + HNSW index present
- ✅ Routes mounted: GET `/`, GET `/api/v1/health`, GET `/api/v1/health/live`, GET/POST `/api/v1/documents`, GET `/api/v1/documents/{id}`, POST `/api/v1/chat`

## What's NOT done (Tasks 23-24)

- ❌ **Task 23: E2E demo** — requires `OPENAI_API_KEY` + `ANTHROPIC_API_KEY` in `.env`. Code is written but not exercised against real APIs.
- ❌ **Task 24: housekeeping** — old deprecated files (qdrant_client, minio_client, workers/, pipeline/, core/{circuit_breaker,fallback_chain,retry}, observability/metrics) still exist; not imported by active code path but not deleted (M2 cleanup).

## How to bring it up (E2E checklist for you)

```bash
# 1. Fill keys
$EDITOR rag-backend/.env       # set OPENAI_API_KEY and ANTHROPIC_API_KEY

# 2. Make sure docker is up
docker compose up -d
docker exec rag_postgres psql -U raguser -d ragdb -c "\dt"
# should see 6 tables including alembic_version

# 3. Start backend (terminal A)
cd rag-backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8088
# or: make dev

# 4. Start frontend (terminal B)
cd rag-frontend && npm run dev
# → http://localhost:3000

# 5. Manual smoke test
# - Visit http://localhost:3000/documents
# - Upload a PDF (any small one)
# - Watch status: queued → parsing → indexed (page_count + chunk_count populate)
# - Visit http://localhost:3000
# - Ask a question about the PDF content; expect [N] citations
```

## Deviations from original plan

1. **Docker port**: 5432 → **5435** (5432 was occupied by another project's container)
2. **001 migration deleted** (vs plan's "keep but ignore"); 002 set `down_revision = None`. Reason: 001's `documents` table schema conflicts with 002's; DB was fresh so no data loss.
3. **Frontend**: skipped Vercel AI Chatbot template clone; built minimal Next.js manually (~250 lines vs ~500MB template). Decision: faster iteration; M2 can adopt template.
4. **Citation schema** lifted to `app/schemas/citation.py` (plan had it in `chat.py` causing circular import with `generation_service.py`).
5. **`health.py` rewritten** (plan said "keep") — original used `get_redis`/`get_qdrant_client` that no longer exist.
6. **Lazy AI clients** in embedding/generation — required so app boots when keys are empty.
7. **`app/models/__init__.py` slimmed** to only Base+5 new models; legacy `feedback.py`/`knowledge_base.py` left on disk but unimported.

## Open issues / M2 candidates

- **Streaming**: backend `/chat` is sync; frontend simulates `loading...` placeholder. M2: add SSE.
- **No reranker, no sparse retrieval**: pure dense cosine. PRD's BGE reranker / Postgres FTS + RRF deferred to M2.
- **No real query rewrite**: multi-turn refs (e.g. "它的违约条款是？") will fail to retrieve. M2.
- **No multi-format parsing**: PDF only. Plan-level M2/M3 add docx/pptx/xlsx/image.
- **No knowledge_base scoping**: all docs in default KB. M2 if multi-KB needed.
- **Deprecated code not removed**: ~1500 LoC dead files for transparency; M2 cleanup task.

## File counts at M1 close

```
Backend:  app/ ~600 LoC active (rewritten/new)  + ~1500 LoC deprecated unused
Frontend: ~250 LoC (4 files)
Migrations: 1 file (002)
Tests: 7 unit tests passing
```
