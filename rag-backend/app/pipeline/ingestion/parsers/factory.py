from __future__ import annotations

from app.pipeline.ingestion.parsers.base import BaseParser


_SUPPORTED_TYPES = {
    "pdf": "pdf_parser",
    "docx": "office_parser",
    "doc": "office_parser",
    "xlsx": "office_parser",
    "xls": "office_parser",
    "pptx": "office_parser",
    "ppt": "office_parser",
    "jpg": "image_parser",
    "jpeg": "image_parser",
    "png": "image_parser",
    "gif": "image_parser",
    "webp": "image_parser",
}


def get_supported_types() -> list[str]:
    return list(_SUPPORTED_TYPES.keys())


class ParserFactory:
    """根据文件类型返回对应的解析器实例"""

    @staticmethod
    def get(file_type: str) -> BaseParser:
        """
        file_type: 文件扩展名（不含点），如 'pdf', 'docx'
        """
        file_type = file_type.lower().lstrip(".")
        parser_key = _SUPPORTED_TYPES.get(file_type)

        if parser_key is None:
            from app.core.exceptions import UnsupportedFileTypeError
            raise UnsupportedFileTypeError(file_type)

        if parser_key == "pdf_parser":
            from app.pipeline.ingestion.parsers.pdf_parser import PDFParser
            return PDFParser()
        elif parser_key == "office_parser":
            from app.pipeline.ingestion.parsers.office_parser import OfficeParser
            return OfficeParser()
        elif parser_key == "image_parser":
            from app.pipeline.ingestion.parsers.image_parser import ImageParser
            return ImageParser()
        else:
            raise ValueError(f"Unknown parser key: {parser_key}")

    @staticmethod
    def is_supported(file_type: str) -> bool:
        return file_type.lower().lstrip(".") in _SUPPORTED_TYPES
