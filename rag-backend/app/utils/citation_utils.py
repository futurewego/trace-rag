import re

_CITATION_RE = re.compile(r"\[(\d+)\]")


def extract_citations(text: str) -> list[int]:
    """从文本中按出现顺序提取 [N] 形式的 citation 索引，去重保序。"""
    seen: set[int] = set()
    out: list[int] = []
    for m in _CITATION_RE.finditer(text):
        n = int(m.group(1))
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out
