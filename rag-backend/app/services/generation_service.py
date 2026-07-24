from collections.abc import Iterator
from functools import lru_cache

from anthropic import Anthropic

from app.config import get_settings
from app.schemas.citation import Citation
from app.services.context_service import ContextBlock
from app.services.retrieval_service import RetrievedChunk
from app.utils.citation_utils import extract_citations

SYSTEM_PROMPT = """你是企业知识库问答助手。严格遵守：
1. 只基于 <context> 标签内的信息回答。
2. 不允许使用 context 之外的知识；不允许说"根据我的知识/通常来说"。
3. 每一个具体事实必须用 [N] 格式标注来源编号，N 对应 context 中的 [文档N]。
4. 如果 context 中找不到答案，明确回答："根据现有知识库无法回答这个问题。" 不要编造。
5. 回答用 Markdown，简明扼要。"""

LOW_CONFIDENCE_NOTE = "⚠️ 检索到的内容相关性较低，请核实。\n\n"


@lru_cache
def _client() -> Anthropic:
    return Anthropic(api_key=get_settings().anthropic_api_key)


def is_low_confidence(chunks: list[RetrievedChunk]) -> bool:
    """低置信提示：仅当所有 chunk 都经过 Cohere 重排（分数已校准）且最高分
    < low_confidence_score 时为真。

    之前用 `settings.cohere_api_key` 是否配置作为"分数已校准"的代理信号，但
    retrieve() 只在 `len(candidates) > top_k` 时才重排，且 Cohere 调用失败会
    降级为融合序（RRF 分，量级 ~0.0098，恒 < 0.6）。因此改为直接读取每个
    RetrievedChunk 上的 `reranked` 标记，而不是再推导一次。用 `all()` 而不是
    `any()`：只要列表中混有未重排的 chunk，说明这批分数不是同一量纲、不可比，
    整体就不能视为"已校准"。
    纯余弦 / RRF 部署下分数不可比，不做低置信判定；无结果属拒答而非低置信。"""
    if not chunks:
        return False
    if not all(c.reranked for c in chunks):
        return False
    s = get_settings()
    return max(c.score for c in chunks) < s.low_confidence_score


def _build_user_prompt(query: str, blocks: list[ContextBlock]) -> str:
    parts = ["<context>"]
    for i, b in enumerate(blocks, start=1):
        page = f" P{b.page_num}" if b.page_num else ""
        sec = f" [{' > '.join(b.section_path)}]" if b.section_path else ""
        parts.append(f"\n[文档{i}] {b.filename}{page}{sec}\n{b.content}\n")
    parts.append("</context>\n")
    parts.append(f"用户问题：{query}")
    return "".join(parts)


def _map_citations(answer: str, blocks: list[ContextBlock]) -> list[Citation]:
    out: list[Citation] = []
    for idx in extract_citations(answer):
        if 1 <= idx <= len(blocks):
            b = blocks[idx - 1]
            out.append(
                Citation(
                    doc_id=b.doc_id,
                    filename=b.filename,
                    page_num=b.page_num,
                    chunk_id=b.chunk_id,
                    score=b.score,
                )
            )
    return out


def generate_answer(
    query: str, blocks: list[ContextBlock], low_confidence: bool = False
) -> tuple[str, list[Citation]]:
    if not blocks:
        return ("根据现有知识库无法回答这个问题。", [])

    settings = get_settings()
    user_prompt = _build_user_prompt(query, blocks)
    resp = _client().messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    answer = resp.content[0].text
    if low_confidence:
        answer = LOW_CONFIDENCE_NOTE + answer
    return (answer, _map_citations(answer, blocks))


def generate_answer_stream(
    query: str, blocks: list[ContextBlock], low_confidence: bool = False
) -> Iterator[tuple[str, str | list[Citation]]]:
    """Generator yielding (event_type, payload).

    event_type:
      - "text"      payload=str (incremental chunk)
      - "citations" payload=list[Citation] (emitted once at stream end)
    """
    if not blocks:
        yield ("text", "根据现有知识库无法回答这个问题。")
        yield ("citations", [])
        return

    settings = get_settings()
    user_prompt = _build_user_prompt(query, blocks)

    if low_confidence:
        yield ("text", LOW_CONFIDENCE_NOTE)

    full_text = ""
    with _client().messages.stream(
        model=settings.anthropic_model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for delta in stream.text_stream:
            full_text += delta
            yield ("text", delta)

    yield ("citations", _map_citations(full_text, blocks))
