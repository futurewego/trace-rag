from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParsedElement:
    """文档中一个解析元素（段落/表格/图片描述）"""
    content: str
    element_type: str               # text | table | image_caption | heading | list
    page_number: int | None = None
    section_path: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    confidence: float = 1.0         # 解析置信度 0-1


@dataclass
class ParsedDocument:
    """解析后的文档，包含所有元素"""
    elements: list[ParsedElement]
    page_count: int = 0
    language: str = "zh"
    title: str | None = None
    parser_used: str = "unknown"
    metadata: dict = field(default_factory=dict)

    @property
    def all_text(self) -> str:
        return "\n\n".join(e.content for e in self.elements if e.content.strip())


class BaseParser(ABC):
    """所有文档解析器的抽象基类"""

    @abstractmethod
    async def parse(self, file_path: Path) -> ParsedDocument:
        """解析文档，返回 ParsedDocument"""
        ...

    @property
    @abstractmethod
    def parser_name(self) -> str:
        """解析器名称，用于 parser_used 字段"""
        ...

    async def can_parse(self, file_path: Path) -> bool:
        """检查是否能处理此文件，默认 True"""
        return True
