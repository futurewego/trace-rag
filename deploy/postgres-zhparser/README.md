# pg-zhparser — PostgreSQL 16 + pgvector + zhparser

Custom Postgres image for trace-rag **P2b hybrid retrieval**: dense vectors
(pgvector) + Chinese sparse full-text (`to_tsvector('zh', …)` via zhparser),
fused with RRF.

## Why a custom image
The stock `pgvector/pgvector:pg16` has no Chinese tokenizer. Postgres' built-in
`simple`/`english` configs treat a run of Chinese (no spaces) as one giant token,
making sparse search useless for zh corpora. zhparser (built on SCWS) segments
Chinese words so `to_tsvector('zh', …)` produces real lexemes.

## Build & run (host with Docker)
```bash
docker build -t trace-rag/pg-zhparser:pg16 deploy/postgres-zhparser
docker run -d --name trace-rag-pg -p 5435:5432 \
  -e POSTGRES_DB=ragdb -e POSTGRES_USER=raguser -e POSTGRES_PASSWORD=ragpass \
  -v trace_rag_pg:/var/lib/postgresql/data \
  trace-rag/pg-zhparser:pg16
```

`init-extensions.sql` provisions `vector` + `zhparser` on first init. The `zh`
text-search configuration and the sparse GIN index are created by the **alembic
migration** (schema lives in code, not the image).

## Verify Chinese segmentation
```sql
CREATE TEXT SEARCH CONFIGURATION zh (PARSER = zhparser);
ALTER TEXT SEARCH CONFIGURATION zh ADD MAPPING FOR n,v,a,i,e,l,j,x,t,z WITH simple;
SELECT to_tsvector('zh', '星曜科技有限公司与黄河智能装备厂签订合同');
-- expect multiple lexemes (星曜/科技/有限公司/黄河/智能/装备厂/签订/合同 …),
-- NOT one blob.
```

## Deploy target
Runs on the LAN host `ubuntu-lan`; the app connects via
`DATABASE_URL=postgresql+psycopg://raguser:ragpass@<ubuntu-lan-ip>:5435/ragdb`.
Host port 5435 matches the project convention and avoids the 5432/5433 already in
use elsewhere.
