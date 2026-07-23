import pytest

pytest.importorskip("testcontainers.postgres")

from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy import text as sa_text
from testcontainers.postgres import PostgresContainer  # noqa: E402

from alembic import command  # noqa: E402


@pytest.fixture(scope="module")
def pg():
    try:
        with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as c:
            yield c
    except Exception as e:  # Docker 不可用
        pytest.skip(f"Docker/testcontainers unavailable: {e}")


def _names(engine, sql, params=None):
    with engine.connect() as c:
        return {r[0] for r in c.execute(sa_text(sql), params or {}).fetchall()}


def _cols(engine, table):
    return _names(
        engine,
        "SELECT column_name FROM information_schema.columns WHERE table_name=:t",
        {"t": table},
    )


def _tables(engine):
    return _names(
        engine,
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'",
    )


def test_migration_003_roundtrip(pg, monkeypatch):
    url = pg.get_connection_url()
    monkeypatch.setenv("DATABASE_URL", url)
    from app.config import get_settings
    get_settings.cache_clear()

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    engine = create_engine(url)

    command.upgrade(cfg, "head")

    with engine.begin() as c:
        c.execute(sa_text(
            "INSERT INTO documents (filename, file_hash, file_path, file_size, status, chunk_count)"
            " VALUES ('a.pdf','h1','/tmp/a.pdf',10,'indexed',0)"
        ))

    assert {"doc_version", "is_latest", "doc_group_id", "knowledge_base_id"} <= _cols(
        engine, "documents"
    )
    assert {
        "chunk_type", "section_path", "parse_confidence", "content_hash",
        "is_latest", "knowledge_base_id", "parent_chunk_id",
    } <= _cols(engine, "chunks")
    assert "parent_chunks" in _tables(engine)

    with engine.connect() as c:
        r = c.execute(sa_text(
            "SELECT id, doc_group_id, doc_version, is_latest FROM documents"
        )).fetchone()
    assert r.doc_group_id == r.id
    assert r.doc_version == 1
    assert r.is_latest is True

    command.downgrade(cfg, "002_m1_schema")
    assert "doc_version" not in _cols(engine, "documents")
    assert "parent_chunk_id" not in _cols(engine, "chunks")
    assert "parent_chunks" not in _tables(engine)

    get_settings.cache_clear()
    engine.dispose()
