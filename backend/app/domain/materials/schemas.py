"""Pydantic-схемы среза materials (МАТ/ВЕРС; один источник моделей, code-standards §2.1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ExternalLink(BaseModel):
    """Внешняя ссылка (МАТ-3): снимок в версии."""

    url: str = Field(min_length=1, max_length=2000)
    label: str = Field(min_length=1, max_length=255)


class MaterialCreate(BaseModel):
    """Поля multipart-запроса POST /groups/{id}/materials (файл — отдельно)."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    attributes: dict | None = None
    external_links: list[ExternalLink] | None = None
    change_comment: str = Field(min_length=1, max_length=2000)


class MaterialPatchContent(BaseModel):
    """PATCH /materials/{id}/content — новая версия (change_comment обязателен, ВЕРС-1)."""

    description: str | None = None
    attributes: dict | None = None
    external_links: list[ExternalLink | None] | None = None
    change_comment: str = Field(min_length=1, max_length=2000)


class MaterialOut(BaseModel):
    """Карточка материала (api-spec §4)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    group_id: uuid.UUID
    name: str
    status: str
    author_id: uuid.UUID
    current_version_id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class VersionOut(BaseModel):
    """Версия в списке/карточке (с метаданными файла)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    material_id: uuid.UUID
    version_no: int
    description: str | None
    external_links: list | None
    attributes: dict | None
    change_comment: str
    created_by: uuid.UUID
    created_at: datetime | None
    file_sha256: str
    chunker_name: str | None = None
    # метаданные файла
    av_status: str | None = None
    text_extracted: str | None = None
    preview_ready: bool = False


class MaterialMove(BaseModel):
    """POST /materials/{id}/move, copy — целевая группа."""

    target_group_id: uuid.UUID


class MaterialLink(BaseModel):
    """POST /materials/{id}/links — привязка родителя (ВЕРС-4)."""

    parent_id: uuid.UUID


class MaterialLinkUpdate(BaseModel):
    """PATCH /materials/{id}/links — перепривязка (фиксирует новую актуальную версию)."""

    parent_version_id: uuid.UUID | None = None
