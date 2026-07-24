-- Provision extensions the app database needs. Runs once on first cluster init
-- (docker-entrypoint-initdb.d), inside POSTGRES_DB.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS zhparser;
-- NOTE: the 'zh' TEXT SEARCH CONFIGURATION and the sparse GIN index are created
-- by the alembic migration (P2b), so schema stays reproducible from code.
