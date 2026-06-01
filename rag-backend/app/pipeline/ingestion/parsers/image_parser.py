from __future__ import annotations

import base64
from pathlib import Path

from app.observability.logger import get_logger
from app.pipeline.ingestion.parsers.base import BaseParser, ParsedDocument, ParsedElement

logger = get_logger(__name__)

VISION_PROMPT = """请详细描述这张图片的内容，包括：
1. 图片的主要内容和主题
2. 如果是图表（折线图/柱状图/饼图等），请提取所有数值、标签、趋势
3. 如果是表格，请以结构化格式输出所有数据
4. 如果包含文字，请完整转录
5. 如果是流程图/架构图，请描述各节点的逻辑关系

请用中文描述，确保信息完整准确，便于后续文本检索。"""


class ImageParser(BaseParser):
    """图片内容理解解析器，使用 Claude Vision 生成描述文本"""

    parser_name = "claude_vision"

    async def parse(self, file_path: Path) -> ParsedDocument:
        import anthropic

        from app.config import get_settings
        settings = get_settings()

        # 读取图片并编码
        with open(file_path, "rb") as f:
            image_data = f.read()
        image_b64 = base64.standard_b64encode(image_data).decode()

        # 确定 media_type
        suffix = file_path.suffix.lower()
        media_type_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        media_type = media_type_map.get(suffix, "image/jpeg")

        try:
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            message = await client.messages.create(
                model=settings.anthropic_model,
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_b64,
                                },
                            },
                            {"type": "text", "text": VISION_PROMPT},
                        ],
                    }
                ],
            )
            description = message.content[0].text

            logger.info("image_parsed_vision", path=str(file_path), chars=len(description))

            element = ParsedElement(
                content=description,
                element_type="image_caption",
                metadata={
                    "original_file": file_path.name,
                    "image_size_bytes": len(image_data),
                },
                confidence=0.85,
            )
            return ParsedDocument(
                elements=[element],
                parser_used="claude_vision",
                metadata={"image_file": file_path.name},
            )

        except Exception as e:
            logger.exception("image_vision_failed", path=str(file_path), error=str(e))
            # 降级：返回文件名作为描述
            element = ParsedElement(
                content=f"图片文件：{file_path.name}（内容解析失败）",
                element_type="image_caption",
                confidence=0.1,
            )
            return ParsedDocument(elements=[element], parser_used="fallback_filename")
