"""多轮追问的查询改写（指代消解）。

改写只服务于【检索】：把"那乙方呢？"结合历史改写成"HT-2026-0087 合同的乙方是谁"
再去召回；生成侧仍使用用户原话 + 完整历史。任何失败都回落原句（PRD 降级 L5）。

与 Pipeline B 的 query_rewriter 三处刻意不同：
- 同步、无 Redis 缓存（同一"问题+历史"几乎不重复，不值得引入基建）；
- 合理性检查用绝对上限 rewrite_max_chars，不用 len(query)*3——中文短问句
  （"乙方呢"×3=9 字）会把所有正确改写误杀；
- 复用 generation_service._client()，不自建第二个 Anthropic 客户端。
"""
from __future__ import annotations

import logging

from app.config import get_settings
from app.services.generation_service import _client

logger = logging.getLogger(__name__)

REWRITE_PROMPT = """你是一个查询改写助手。用户正在进行多轮对话，请根据对话历史，把当前问题改写为一个独立完整的检索查询。

要求：
1. 解析所有代词和指代（"它"、"这个"、"那个产品"、"呢"等）
2. 保留用户原本的意图，不要改变语义
3. 输出一个无需对话历史即可理解的独立查询
4. 只输出改写后的查询本身，不要任何解释或前缀

对话历史：
{history}

当前问题：{question}

改写后的查询："""


def rewrite_query(query: str, history: list[dict]) -> str:
    """把含指代的追问改写为独立检索查询；任何异常或不合理结果回落原 query。"""
    settings = get_settings()
    if not settings.enable_query_rewrite or not history:
        return query

    try:
        history_text = "\n".join(
            f"{'用户' if m['role'] == 'user' else 'AI'}: {m['content']}" for m in history
        )
        prompt = REWRITE_PROMPT.format(history=history_text, question=query)

        resp = _client().messages.create(
            model=settings.anthropic_model,
            max_tokens=256,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        rewritten = (resp.content[0].text or "").strip()
    except Exception as e:
        logger.warning("query rewrite failed, using original: %s", e)
        return query

    # 模型偶尔附带解释：只取首行
    rewritten = rewritten.splitlines()[0].strip() if rewritten else ""

    if not rewritten or len(rewritten) > settings.rewrite_max_chars:
        logger.warning(
            "query rewrite unreasonable (len=%d), using original", len(rewritten)
        )
        return query
    return rewritten
