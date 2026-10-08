"""Хранилище клипов: S3-совместимое (MinIO/AWS/Yandex Object Storage) или локальная папка.

Клиент всегда получает короткоживущий подписанный URL.
"""

from __future__ import annotations

import shutil
import time
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from .config import settings
from .security import sign_media


@lru_cache(maxsize=1)
def _s3_clients():
    import boto3
    from botocore.config import Config

    cfg = Config(signature_version="s3v4", s3={"addressing_style": "path"})
    common = dict(
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=cfg,
    )
    internal = boto3.client("s3", endpoint_url=settings.s3_endpoint, **common)
    # Подпись включает хост, поэтому URL для браузера подписываем публичным адресом.
    public = boto3.client("s3", endpoint_url=settings.s3_public_endpoint, **common)
    return internal, public


def signed_url(key: str) -> str:
    if settings.storage_backend == "s3":
        _, public = _s3_clients()
        return public.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket, "Key": key},
            ExpiresIn=settings.clip_url_ttl,
        )
    expires = int(time.time()) + settings.clip_url_ttl
    return f"/api/media/{quote(key)}?exp={expires}&sig={sign_media(key, expires)}"


def local_path(key: str) -> Path | None:
    base = Path(settings.media_dir).resolve()
    path = (base / key).resolve()
    if base not in path.parents or not path.is_file():
        return None
    return path


def put_file(src: Path, key: str) -> None:
    if settings.storage_backend == "s3":
        internal, _ = _s3_clients()
        try:
            internal.head_bucket(Bucket=settings.s3_bucket)
        except Exception:
            internal.create_bucket(Bucket=settings.s3_bucket)
        internal.upload_file(
            str(src), settings.s3_bucket, key,
            ExtraArgs={"ContentType": "video/mp4", "CacheControl": "private, max-age=600"},
        )
        return
    dst = Path(settings.media_dir) / key
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
