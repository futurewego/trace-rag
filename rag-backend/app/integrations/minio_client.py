from __future__ import annotations

import asyncio
import io
from pathlib import Path

from minio import Minio
from minio.error import S3Error

from app.config import get_settings
from app.core.exceptions import StorageError
from app.core.retry import with_retry
from app.observability.logger import get_logger

logger = get_logger(__name__)

# 延迟初始化单例
_client: Minio | None = None


def get_minio_client() -> Minio:
    global _client
    if _client is None:
        settings = get_settings()
        _client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        # 确保 bucket 存在
        try:
            if not _client.bucket_exists(settings.minio_bucket):
                _client.make_bucket(settings.minio_bucket)
                logger.info("minio_bucket_created", bucket=settings.minio_bucket)
        except S3Error as e:
            logger.warning("minio_bucket_check_failed", error=str(e))
    return _client


class MinIOClient:
    """MinIO/OSS 文件存储客户端，所有方法均为异步（通过 asyncio.to_thread 包裹同步 SDK）"""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._bucket = self._settings.minio_bucket

    @property
    def _client(self) -> Minio:
        return get_minio_client()

    async def upload_file(self, data: bytes, object_name: str, content_type: str = "application/octet-stream") -> str:
        """上传文件，返回 object_name（存储路径）"""
        try:
            await asyncio.to_thread(
                self._client.put_object,
                self._bucket,
                object_name,
                io.BytesIO(data),
                len(data),
                content_type=content_type,
            )
            logger.info("minio_upload_ok", object_name=object_name, size=len(data))
            return object_name
        except S3Error as e:
            logger.exception("minio_upload_failed", object_name=object_name, error=str(e))
            raise StorageError(f"Failed to upload {object_name}: {e}") from e

    async def upload_file_path(self, file_path: Path, object_name: str) -> str:
        """从本地路径上传文件"""
        try:
            await asyncio.to_thread(
                self._client.fput_object,
                self._bucket,
                object_name,
                str(file_path),
            )
            logger.info("minio_upload_path_ok", object_name=object_name)
            return object_name
        except S3Error as e:
            raise StorageError(f"Failed to upload {file_path}: {e}") from e

    async def download_file(self, object_name: str) -> bytes:
        """下载文件，返回 bytes"""
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                self._bucket,
                object_name,
            )
            data = await asyncio.to_thread(response.read)
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            raise StorageError(f"Failed to download {object_name}: {e}") from e

    async def download_to_path(self, object_name: str, dest_path: Path) -> None:
        """下载文件到本地路径"""
        try:
            await asyncio.to_thread(
                self._client.fget_object,
                self._bucket,
                object_name,
                str(dest_path),
            )
        except S3Error as e:
            raise StorageError(f"Failed to download {object_name} to {dest_path}: {e}") from e

    async def delete_file(self, object_name: str) -> None:
        """删除文件"""
        try:
            await asyncio.to_thread(self._client.remove_object, self._bucket, object_name)
            logger.info("minio_delete_ok", object_name=object_name)
        except S3Error as e:
            logger.warning("minio_delete_failed", object_name=object_name, error=str(e))

    async def get_presigned_url(self, object_name: str, expires_hours: int = 24) -> str:
        """生成预签名 URL，用于 Citation 跳转"""
        from datetime import timedelta
        try:
            url = await asyncio.to_thread(
                self._client.presigned_get_object,
                self._bucket,
                object_name,
                expires=timedelta(hours=expires_hours),
            )
            return url
        except S3Error as e:
            raise StorageError(f"Failed to generate presigned URL for {object_name}: {e}") from e

    async def file_exists(self, object_name: str) -> bool:
        """检查文件是否存在"""
        try:
            await asyncio.to_thread(self._client.stat_object, self._bucket, object_name)
            return True
        except S3Error:
            return False
