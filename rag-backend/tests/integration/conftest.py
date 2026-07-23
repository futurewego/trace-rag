import os

# The migration round-trip test drives app.config.Settings (via alembic/env.py),
# which requires OPENAI_API_KEY / ANTHROPIC_API_KEY to construct at all, even
# though the migration itself never touches them. Provide inert dummies so the
# suite runs on a clean checkout with no .env. setdefault keeps any real env wins.
# DATABASE_URL is intentionally NOT defaulted here: the test itself sets it via
# monkeypatch to point at the ephemeral testcontainer before invoking alembic.
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")
