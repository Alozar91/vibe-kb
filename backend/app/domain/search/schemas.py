"""Pydantic-схемы поиска (api-spec §5)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class SearchFilters(BaseModel):
    """Фильтры выдачи (mode=attributes и как пост-фильтр)."""

    attributes: dict | None = None
    status: list[str] | None = None
    author_id: uuid.UUID | None = None
    date_from: str | None = None
    date_to: str | None = None


class SearchIn(BaseModel):
    """POST /api/v1/search (api-spec §5)."""

    query: str | None = None  # обязателен для fulltext/vector/hybrid
    mode: str = Field(default="fulltext", pattern="^(fulltext|vector|hybrid|attributes)$")
    group_ids: list[uuid.UUID] | None = None
    filters: SearchFilters | None = None
    top_k: int = Field(default=20, ge=1, le=100)


class SearchHit(BaseModel):
    """Результат поиска."""

    type: str  # "material" | "group"
    material_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    name: str
    snippet: str | None = None
    chunk: str | None = None
    version_id: uuid.UUID | None = None
    chunk_index: int | None = None
    score: float = 0.0


class SearchOut(BaseModel):
    results: list[SearchHit]
    total: int
