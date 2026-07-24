"""对真实 zhparser 库验证中文稀疏检索（需迁移 004 已执行）。

用法：
    DATABASE_URL='postgresql+psycopg://raguser:ragpass@192.168.5.31:5435/ragdb' \
    OPENAI_API_KEY=x ANTHROPIC_API_KEY=x \
    .venv/bin/python -m scripts.verify_sparse
"""
from __future__ import annotations

from sqlalchemy import text

from app.dependencies import _SessionLocal
from app.services.retrieval_service import _sparse_candidates

DOC_SQL = """
INSERT INTO documents (filename, file_hash, file_path, file_size, status, chunk_count)
VALUES ('p2b_probe.pdf', 'p2b-probe-hash', '/tmp/p2b_probe.pdf', 1, 'indexed', 1)
ON CONFLICT (file_hash) DO UPDATE SET filename = EXCLUDED.filename
RETURNING id
"""

CHUNK_SQL = """
INSERT INTO chunks (document_id, chunk_index, content, page_num, token_count,
                    embedding, chunk_type, is_latest)
VALUES (:doc_id, 0,
        '星曜科技有限公司与黄河智能装备厂签订合同，合同编号 HT-2026-0087，金额壹佰贰拾伍万元。',
        1, 40, :vec, 'text', true)
RETURNING id
"""


def main() -> None:
    with _SessionLocal() as db:
        doc_id = db.execute(text(DOC_SQL)).scalar_one()
        vec = "[" + ",".join(["0"] * 1536) + "]"
        chunk_id = db.execute(
            text(CHUNK_SQL), {"doc_id": doc_id, "vec": vec}
        ).scalar_one()
        db.commit()
        print(f"probe doc={doc_id} chunk={chunk_id}")

        for q in ["合同编号", "星曜科技", "黄河智能装备", "HT-2026-0087"]:
            hits = _sparse_candidates(db, q, limit=5)
            ok = any(h.chunk_id == chunk_id for h in hits)
            print(f"query={q!r:20} hits={len(hits)} matched_probe={ok}")

        # cleanup
        db.execute(text("DELETE FROM chunks WHERE id = :cid"), {"cid": chunk_id})
        db.execute(text("DELETE FROM documents WHERE id = :did"), {"did": doc_id})
        db.commit()
        print("probe rows cleaned up")


if __name__ == "__main__":
    main()
