from __future__ import annotations

import hashlib
import json

from app.config import get_settings
from app.observability.logger import get_logger

logger = get_logger(__name__)

REWRITE_PROMPT = """你是一个查询改写助手。用户正在进行多轮对话，请根据对话历史，将当前问题改写为一个独立完整的检索查询。

要求：
1. 解析所有代词和指代（"它"、"这个"、"那个产品"等）
2. 保留用户原本的意图，不要改变语义
3. 输出一个独立的查询字符串，无需对话历史即可理解
4. 只输出改写后的查询，不要解释

对话历史：
{history}

当前问题：{question}

改写后的查询："""


class QueryRewriter:
    """
    使用 Claude 对含指代的问题进行改写，使其成为独立完整的检索查询。
    结果缓存到 Redis（TTL 5分钟），相同问题+历史不重复调用 LLM。
    """

    def __init__(self) -> None:
        self._settings = get_settings()

    def _cache_key(self, query: str, history: list[dict]) -> str:
        content = json.dumps({"q": query, "h": history[-3:]}, ensure_ascii=False)
        return f"qrewrite:{hashlib.sha256(content.encode()).hexdigest()}"

    async def rewrite(self, query: str, history: list[dict]) -> str:
        """
        改写查询。
        - 无历史时直接返回原始查询
        - 改写失败时返回原始查询（降级 L6）
        """
        if not history:
            return query

        # 检查缓存
        try:
            from app.dependencies import get_redis
            redis = await get_redis()
            cache_key = self._cache_key(query, history)
            cached = await redis.get(cache_key)
            if cached:
                logger.debug("query_rewrite_cache_hit", key=cache_key[:20])
                return cached
        except Exception:
            pass  # Redis 不可用时继续

        # 构建历史摘要（最近 3 轮）
        history_text = "\n".join(
            f"{'用户' if m['role'] == 'user' else 'AI'}: {m['content'][:200]}"
            for m in history[-6:]
        )

        prompt = REWRITE_PROMPT.format(history=history_text, question=query)

        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=self._settings.anthropic_api_key)
            message = await client.messages.create(
                model=self._settings.anthropic_model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            rewritten = message.content[0].text.strip()

            # 合理性检查：改写结果不能太短或太长
            if len(rewritten) < 5 or len(rewritten) > len(query) * 3:
                logger.warning("query_rewrite_unreasonable", original=query, rewritten=rewritten)
                return query

            # 写入缓存（TTL 5分钟）
            try:
                await redis.setex(cache_key, 300, rewritten)
            except Exception:
                pass

            logger.debug("query_rewrite_done", original=query[:60], rewritten=rewritten[:60])
            return rewritten

        except Exception as e:
            logger.warning("query_rewrite_failed", error=str(e), query=query[:60])
            return query  # 降级：返回原始查询
