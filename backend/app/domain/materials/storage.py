"""Клиент объектного хранилища Silo (S3-совместимый; deployment.md §1, АDR нет — boto3).

Хранение: bucket kb-files (оригиналы), kb-previews (PDF-превью).
Ключ объекта: files/{sha256}/{size}/{filename} — дедупликация на уровне ключей.
"""

from __future__ import annotations

import hashlib
from typing import Any

import boto3
from botocore.client import Config as BotoConfig

from app.common.config import get_settings


def _client() -> Any:
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        config=BotoConfig(signature_version="s3v4"),
        region_name="us-east-1",
    )


def storage_key(sha256: str, size: int, filename: str) -> str:
    """Ключ объекта: дедупликация по sha256+size (ВЕРС-2)."""

    safe = filename.replace("/", "_").replace("\\", "_")[:120]
    return f"files/{sha256}/{size}/{safe}"


def upload_bytes(content: bytes, filename: str) -> tuple[str, str, int]:
    """Загрузить содержимое; вернуть (storage_key, sha256, size)."""

    sha256 = hashlib.sha256(content).hexdigest()
    size = len(content)
    key = storage_key(sha256, size, filename)
    _client().put_object(
        Bucket=get_settings().s3_bucket_files, Key=key, Body=content
    )
    return key, sha256, size


def download_bytes(storage_key: str) -> bytes:
    """Скачать оригинал (только после AV-гейта, НФТ-4 — проверяется сервисом)."""

    resp = _client().get_object(Bucket=get_settings().s3_bucket_files, Key=storage_key)
    return resp["Body"].read()


def upload_preview(content: bytes, preview_key: str) -> None:
    """Загрузить PDF-превью (пишется атомарно после генерации, data-model §6)."""

    _client().put_object(Bucket=get_settings().s3_bucket_previews, Key=preview_key, Body=content)


def download_preview(preview_key: str) -> bytes | None:
    """Скачать превью; нет объекта → None (202 pending в API)."""

    try:
        resp = _client().get_object(Bucket=get_settings().s3_bucket_previews, Key=preview_key)
        return resp["Body"].read()
    except _client().exceptions.NoSuchKey:
        return None
