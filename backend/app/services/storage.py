import os
import tempfile
import uuid
from functools import lru_cache
from urllib.parse import urlparse

import boto3
import httpx
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import settings


class StorageError(Exception):
    pass


def _require_r2_config() -> None:
    missing = [
        name
        for name, value in (
            ("R2_ACCOUNT_ID", settings.r2_account_id),
            ("R2_ACCESS_KEY_ID", settings.r2_access_key_id),
            ("R2_SECRET_ACCESS_KEY", settings.r2_secret_access_key),
            ("R2_BUCKET", settings.r2_bucket),
            ("R2_ENDPOINT", settings.r2_endpoint),
        )
        if not value
    ]
    if missing:
        raise StorageError(
            f"R2 物件儲存尚未設定，缺少環境變數：{', '.join(missing)}"
        )


@lru_cache(maxsize=1)
def _client():
    _require_r2_config()
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def _extract_extension(url: str) -> str:
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    if ext and len(ext) <= 6:
        return ext.lower()
    return ".mp3"


def upload_from_url(source_url: str) -> str:
    _require_r2_config()
    ext = _extract_extension(source_url)
    key = f"audio/{uuid.uuid4()}{ext}"

    try:
        with httpx.stream(
            "GET", source_url, timeout=120.0, follow_redirects=True
        ) as response:
            if response.status_code != 200:
                raise StorageError(
                    f"下載音檔失敗：HTTP {response.status_code} ({source_url})"
                )
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                tmp_path = tmp.name
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    tmp.write(chunk)
    except httpx.HTTPError as exc:
        raise StorageError(f"下載音檔失敗：{exc}") from exc

    try:
        _client().upload_file(tmp_path, settings.r2_bucket, key)
    except ClientError as exc:
        raise StorageError(f"上傳 R2 失敗：{exc}") from exc
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return key


def download_to_temp(storage_key: str) -> str:
    _require_r2_config()
    _, ext = os.path.splitext(storage_key)
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext or ".bin") as tmp:
        tmp_path = tmp.name

    try:
        _client().download_file(settings.r2_bucket, storage_key, tmp_path)
    except ClientError as exc:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise StorageError(f"R2 下載失敗 (key={storage_key})：{exc}") from exc

    return tmp_path


def get_presigned_url(storage_key: str, expires_in: int = 3600) -> str:
    _require_r2_config()
    try:
        return _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.r2_bucket, "Key": storage_key},
            ExpiresIn=expires_in,
        )
    except ClientError as exc:
        raise StorageError(f"產生 presigned URL 失敗：{exc}") from exc
