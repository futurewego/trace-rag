import io
import json
import logging
from functools import lru_cache

from alibabacloud_ocr_api20210707 import models as ocr_models
from alibabacloud_ocr_api20210707.client import Client as OcrClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util.models import RuntimeOptions

from app.config import get_settings

logger = logging.getLogger(__name__)


class OcrError(Exception):
    """OCR 调用失败的统一异常。"""


def ocr_enabled() -> bool:
    s = get_settings()
    return bool(s.aliyun_ocr_access_key_id and s.aliyun_ocr_access_key_secret)


@lru_cache
def _client() -> OcrClient:
    s = get_settings()
    config = open_api_models.Config(
        access_key_id=s.aliyun_ocr_access_key_id,
        access_key_secret=s.aliyun_ocr_access_key_secret,
        endpoint=s.aliyun_ocr_endpoint,
    )
    return OcrClient(config)


def ocr_image(image_bytes: bytes) -> str:
    """单张图像 → 文本；失败抛 OcrError。

    Args:
        image_bytes: JPEG 或 PNG 字节流。

    Returns:
        识别出的文本（空字符串若图像无文字）。

    Raises:
        OcrError: SDK 调用失败 / 返回非预期结构 / 服务异常。
    """
    if not ocr_enabled():
        raise OcrError("OCR not enabled (Aliyun key missing)")

    # A single io.BytesIO is safe only because autoretry is off. If retries are
    # ever enabled on RuntimeOptions, the stream would be re-read at EOF and an
    # empty body signed/sent — recreate the BytesIO per attempt in that case.
    request = ocr_models.RecognizeGeneralRequest(body=io.BytesIO(image_bytes))
    # Explicit timeouts (ms) so a slow/hung call cannot stall ingestion; these
    # match Tea's 5s/10s defaults, surfaced here on purpose.
    runtime = RuntimeOptions(connect_timeout=5000, read_timeout=10000)
    try:
        resp = _client().recognize_general_with_options(request, runtime)
        data = json.loads(resp.body.data) if resp.body.data else {}
        return data.get("content", "") or ""
    except Exception as e:
        raise OcrError(str(e)) from e
