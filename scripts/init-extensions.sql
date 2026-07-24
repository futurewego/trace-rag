CREATE EXTENSION IF NOT EXISTS vector;
-- zhparser: required by alembic migration 004_p2b_sparse (P2b Chinese sparse
-- retrieval). Provided by the custom deploy/postgres-zhparser image — this
-- file is bind-mounted over the image's own init script, so it must still
-- create both extensions.
CREATE EXTENSION IF NOT EXISTS zhparser;
