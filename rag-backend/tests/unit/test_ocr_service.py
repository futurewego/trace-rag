import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.ocr_service import OcrError, ocr_enabled, ocr_image


def _make_mock_response(content: str) -> MagicMock:
    """阿里云 OCR SDK 的返回结构：response.body.data 是 JSON string."""
    resp = MagicMock()
    resp.body.data = json.dumps({"content": content})
    return resp


@patch("app.services.ocr_service._client")
@patch("app.services.ocr_service.ocr_enabled", return_value=True)
def test_ocr_image_success(mock_enabled: MagicMock, mock_client: MagicMock) -> None:
    mock_client.return_value.recognize_general_with_options.return_value = (
        _make_mock_response("hello world")
    )

    text = ocr_image(b"\xff\xd8\xff\xe0fake-jpeg-bytes")

    assert text == "hello world"
    mock_client.return_value.recognize_general_with_options.assert_called_once()


@patch("app.services.ocr_service._client")
@patch("app.services.ocr_service.ocr_enabled", return_value=True)
def test_ocr_image_api_error_wrapped(mock_enabled: MagicMock, mock_client: MagicMock) -> None:
    mock_client.return_value.recognize_general_with_options.side_effect = RuntimeError(
        "Aliyun 5xx"
    )

    with pytest.raises(OcrError) as exc:
        ocr_image(b"jpeg-bytes")

    assert "Aliyun 5xx" in str(exc.value)


def test_ocr_enabled_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALIYUN_OCR_ACCESS_KEY_ID", "fake-id")
    monkeypatch.setenv("ALIYUN_OCR_ACCESS_KEY_SECRET", "fake-secret")
    from app.config import get_settings

    get_settings.cache_clear()
    assert ocr_enabled() is True
    get_settings.cache_clear()


def test_ocr_enabled_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALIYUN_OCR_ACCESS_KEY_ID", "")
    monkeypatch.setenv("ALIYUN_OCR_ACCESS_KEY_SECRET", "")
    from app.config import get_settings

    get_settings.cache_clear()
    assert ocr_enabled() is False
    get_settings.cache_clear()
