from functools import lru_cache

from anthropic import Anthropic

from app.config import get_settings
from app.schemas.citation import Citation
from app.services.retrieval_service import RetrievedChunk
from app.utils.citation_utils import extract_citations

SYSTEM_PROMPT = """你是企业知识库问答助手。严格遵守：
1. 只基于 <context> 标签内的信息回答。
2. 不允许使用 context 之外的知识；不允许说"根据我的知识/通常来说"。
3. 每一个具体事实必须用 [N] 格式标注来源编号，N 对应 context 中的 [文档N]。
4. 如果 context 中找不到答案，明确回答："根据现有知识库无法回答这个问题。" 不要编造。
5. 回答用 Markdown，简明扼要。"""


@lru_cache
def _client() -> Anthropic:
    return Anthropic(api_key=get_settings().anthropic_api_key)


def _build_user_prompt(query: str, chunks: list[RetrievedChunk]) -> str:
    parts = ["<context>"]
    for i, ck in enumerate(chunks, start=1):
        page = f" P{ck.page_num}" if ck.page_num else ""
        parts.append(f"\n[文档{i}] {ck.filename}{page}\n{ck.content}\n")
    parts.append("</context>\n")
    parts.append(f"用户问题：{query}")
    return "".join(parts)


def generate_answer(
    query: str, chunks: list[RetrievedChunk]
) -> tuple[str, list[Citation]]:
    if not chunks:
        return ("根据现有知识库无法回答这个问题。", [])

    settings = get_settings()
    user_prompt = _build_user_prompt(query, chunks)
    resp = _client().messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    answer = resp.content[0].text

    citation_indices = extract_citations(answer)
    citations: list[Citation] = []
    for idx in citation_indices:
        if 1 <= idx <= len(chunks):
            ck = chunks[idx - 1]
            citations.append(
                Citation(
                    doc_id=ck.doc_id,
                    filename=ck.filename,
                    page_num=ck.page_num,
                    chunk_id=ck.chunk_id,
                    score=ck.score,
                )
            )
    return (answer, citations)
