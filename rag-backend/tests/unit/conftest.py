import os

# Unit tests mock every external client (OpenAI / Anthropic / Aliyun OCR), but
# app.config.Settings still *requires* these fields to construct at all. Provide
# inert dummies so the unit suite runs on a clean checkout with no .env (real
# values come from .env for integration/E2E). setdefault keeps any real env wins.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://test:test@localhost:5435/testdb"
)
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")
