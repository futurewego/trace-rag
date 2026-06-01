from __future__ import annotations

import asyncio
from pathlib import Path

from app.observability.logger import get_logger
from app.pipeline.ingestion.parsers.base import BaseParser, ParsedDocument, ParsedElement

logger = get_logger(__name__)


class PDFParser(BaseParser):
    """
    PDF 解析器：主路 Unstructured，失败 fallback 到 Azure Document Intelligence。
    """

    parser_name = "pdf_parser"

    async def parse(self, file_path: Path) -> ParsedDocument:
        # 主路：Unstructured
        try:
            result = await self._parse_with_unstructured(file_path)
            logger.info("pdf_parsed_unstructured", path=str(file_path), elements=len(result.elements))
            return result
        except Exception as e:
            logger.warning("pdf_unstructured_failed", path=str(file_path), error=str(e))

        # Fallback：Azure Document Intelligence
        from app.config import get_settings
        if get_settings().azure_di_enabled:
            try:
                result = await self._parse_with_azure_di(file_path)
                logger.info("pdf_parsed_azure_di", path=str(file_path), elements=len(result.elements))
                return result
            except Exception as e:
                logger.warning("pdf_azure_di_failed", path=str(file_path), error=str(e))

        # 最终 fallback：简单文本提取
        return await self._parse_basic(file_path)

    async def _parse_with_unstructured(self, file_path: Path) -> ParsedDocument:
        """使用 Unstructured 解析 PDF"""
        from unstructured.partition.pdf import partition_pdf

        def _sync_parse():
            elements = partition_pdf(
                filename=str(file_path),
                strategy="hi_res",
                infer_table_structure=True,
                include_page_breaks=True,
            )
            return elements

        raw_elements = await asyncio.to_thread(_sync_parse)

        parsed_elements = []
        current_section: list[str] = []
        page_count = 0

        for el in raw_elements:
            el_type = type(el).__name__.lower()
            page_num = getattr(el.metadata, "page_number", None)
            if page_num:
                page_count = max(page_count, page_num)

            # 推断 chunk type
            if "table" in el_type:
                chunk_type = "table"
            elif "title" in el_type or "header" in el_type:
                chunk_type = "heading"
                if el.text.strip():
                    current_section = [el.text.strip()]
            elif "image" in el_type:
                chunk_type = "image_caption"
            else:
                chunk_type = "text"

            content = el.text if hasattr(el, "text") else str(el)
            if not content.strip():
                continue

            parsed_elements.append(
                ParsedElement(
                    content=content,
                    element_type=chunk_type,
                    page_number=page_num,
                    section_path=list(current_section),
                    confidence=0.9,
                )
            )

        return ParsedDocument(
            elements=parsed_elements,
            page_count=page_count,
            parser_used="unstructured",
        )

    async def _parse_with_azure_di(self, file_path: Path) -> ParsedDocument:
        """使用 Azure Document Intelligence 解析（适合复杂表格/扫描件）"""
        from azure.ai.formrecognizer.aio import DocumentAnalysisClient
        from azure.core.credentials import AzureKeyCredential

        from app.config import get_settings
        settings = get_settings()

        client = DocumentAnalysisClient(
            endpoint=settings.azure_di_endpoint,
            credential=AzureKeyCredential(settings.azure_di_key),
        )

        async with client:
            with open(file_path, "rb") as f:
                poller = await client.begin_analyze_document("prebuilt-document", f)
            result = await poller.result()

        parsed_elements = []
        page_count = len(result.pages) if result.pages else 0

        for para in (result.paragraphs or []):
            page_num = para.bounding_regions[0].page_number if para.bounding_regions else None
            parsed_elements.append(
                ParsedElement(
                    content=para.content,
                    element_type="text",
                    page_number=page_num,
                    confidence=0.95,
                )
            )

        for table in (result.tables or []):
            page_num = table.bounding_regions[0].page_number if table.bounding_regions else None
            # 将表格转换为 Markdown
            md_rows = []
            max_col = max((cell.column_index for cell in table.cells), default=0) + 1
            grid: dict[tuple[int, int], str] = {}
            for cell in table.cells:
                grid[(cell.row_index, cell.column_index)] = cell.content

            for row_idx in range(table.row_count):
                row = [grid.get((row_idx, col_idx), "") for col_idx in range(max_col)]
                md_rows.append("| " + " | ".join(row) + " |")
                if row_idx == 0:
                    md_rows.append("| " + " | ".join(["---"] * max_col) + " |")

            parsed_elements.append(
                ParsedElement(
                    content="\n".join(md_rows),
                    element_type="table",
                    page_number=page_num,
                    confidence=0.95,
                )
            )

        return ParsedDocument(
            elements=parsed_elements,
            page_count=page_count,
            parser_used="azure_di",
        )

    async def _parse_basic(self, file_path: Path) -> ParsedDocument:
        """最基础的 PDF 文本提取（pypdf），作为最终 fallback"""
        try:
            import pypdf

            def _sync():
                reader = pypdf.PdfReader(str(file_path))
                elements = []
                for i, page in enumerate(reader.pages, 1):
                    text = page.extract_text() or ""
                    if text.strip():
                        elements.append(
                            ParsedElement(
                                content=text,
                                element_type="text",
                                page_number=i,
                                confidence=0.6,
                            )
                        )
                return elements, len(reader.pages)

            elements, page_count = await asyncio.to_thread(_sync)
            logger.warning("pdf_fallback_basic_parser_used", path=str(file_path))
            return ParsedDocument(elements=elements, page_count=page_count, parser_used="pypdf_basic")
        except Exception as e:
            raise RuntimeError(f"All PDF parsers failed for {file_path}: {e}") from e
