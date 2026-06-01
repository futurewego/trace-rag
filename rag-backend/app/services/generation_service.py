from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from app.config import get_settings
from app.core.fallback_chain import FallbackChain
from app.observability.logger import get_logger
from app.observability.metrics import fallback_total, generation_latency
from app.pipeline.retrieval.reranker import RankedResult
from app.utils.citation_utils import (
    Citation,
    build_system_prompt,
    citations_to_dict,
    parse_citations,
)

logger = get_logger(__name__)


@dataclass
class StreamEvent:
    event_type: str   # retrieval_start | retrieval_done | generation_start | token | citation | done | error
    data: dict


class GenerationService:
    """
    LLM 生成服务，使用 FallbackChain：
    主力：Claude 3.5 Sonnet
    备用：GPT-4o
    最终降级：返回原始 chunk 内容（无 LLM 生成）
    """

    def __init__(self) -> None:
        self._settings = get_settings()

    async def generate_stream(
        self,
        query: str,
        chunks: list[RankedResult],
        chat_history: list[dict],
        model_override: str | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """流式生成，yield StreamEvent 序列"""
        if not chunks:
            yield StreamEvent(
                event_type="done",
                data={
                    "message": "知识库中暂无相关内容，请尝试换个问法或扩大知识库范围。",
                    "citations": [],
                    "model": "none",
                    "empty_retrieval": True,
                },
            )
            return

        system_prompt = build_system_prompt(chunks)
        messages = self._build_messages(chat_history, query)

        full_response = ""
        t0 = time.monotonic()

        try:
            # 尝试 Claude
            async for chunk_text in self._stream_anthropic(system_prompt, messages):
                full_response += chunk_text
                yield StreamEvent(event_type="token", data={"delta": chunk_text})
            model_used = self._settings.anthropic_model

        except Exception as e:
            logger.warning("anthropic_stream_failed_trying_gpt4o", error=str(e))
            fallback_total.labels(service="anthropic", reason="stream_error").inc()
            full_response = ""

            try:
                # Fallback：GPT-4o
                async for chunk_text in self._stream_openai(system_prompt, messages):
                    full_response += chunk_text
                    yield StreamEvent(event_type="token", data={"delta": chunk_text})
                model_used = self._settings.openai_chat_model

            except Exception as e2:
                logger.warning("gpt4o_stream_failed_raw_chunks", error=str(e2))
                fallback_total.labels(service="gpt4o", reason="stream_error").inc()

                # 最终降级：返回原始 chunk 内容
                raw_content = "\n\n---\n\n".join(
                    f"**{r.payload.get('document_name', '未知文档')}**"
                    f"（第{r.payload.get('page_number', '?')}页）\n{r.payload.get('content', '')}"
                    for r in chunks[:3]
                )
                yield StreamEvent(
                    event_type="token",
                    data={"delta": f"[AI生成服务暂不可用，以下为原文摘录]\n\n{raw_content}"},
                )
                full_response = raw_content
                model_used = "raw_chunks"

        elapsed = time.monotonic() - t0
        generation_latency.labels(model=model_used).observe(elapsed)

        # 解析 citation
        citations: list[Citation] = parse_citations(full_response, chunks)

        # 为每个 citation 生成预签名 URL
        for citation in citations:
            yield StreamEvent(
                event_type="citation",
                data={
                    "index": citation.index,
                    "chunk_id": citation.chunk_id,
                    "document_id": citation.document_id,
                    "document_name": citation.document_name,
                    "page_number": citation.page_number,
                    "snippet": citation.snippet,
                },
            )

        yield StreamEvent(
            event_type="done",
            data={
                "model": model_used,
                "citations": citations_to_dict(citations),
                "latency_ms": int(elapsed * 1000),
            },
        )

    async def _stream_anthropic(
        self, system_prompt: str, messages: list[dict]
    ) -> AsyncGenerator[str, None]:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self._settings.anthropic_api_key)
        async with client.messages.stream(
            model=self._settings.anthropic_model,
            max_tokens=self._settings.anthropic_max_tokens,
            system=system_prompt,
            messages=messages,
            temperature=0.1,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def _stream_openai(
        self, system_prompt: str, messages: list[dict]
    ) -> AsyncGenerator[str, None]:
        import openai

        client = openai.AsyncOpenAI(api_key=self._settings.openai_api_key)
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        stream = await client.chat.completions.create(
            model=self._settings.openai_chat_model,
            messages=full_messages,
            max_tokens=4096,
            temperature=0.1,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    def _build_messages(self, history: list[dict], current_query: str) -> list[dict]:
        """构建 LLM messages，保留最近 10 轮"""
        messages = []
        for msg in history[-20:]:  # 最近 10 轮 = 20 条消息
            if msg.get("role") in ("user", "assistant"):
                messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": current_query})
        return messages
