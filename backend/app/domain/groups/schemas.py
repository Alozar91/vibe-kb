"""Pydantic-схемы среза groups (один источник моделей данных, code-standards §2.1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GroupCreate(BaseModel):
    """POST /groups/{id}/children — создание подгруппы."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class GroupUpdate(BaseModel):
    """PATCH /groups/{id} — переименование/описание."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class GroupMove(BaseModel):
    """POST /groups/{id}/move — перемещение."""

    new_parent_id: uuid.UUID | None  # null — сделать корневой


class GroupOut(BaseModel):
    """Группа в выдаче."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    description: str | None
    nav_only: bool = False  # ПРВ-2: предок без содержимого
    created_at: datetime | None = None


class GroupNode(GroupOut):
    """Узел дерева: дети подгружаются отдельным запросом."""

    pass


class RoleAssign(BaseModel):
    """PUT /groups/{id}/roles/{user_id}."""

    role: str = Field(pattern="^(reader|editor|reviewer|owner)$")


class RoleOut(BaseModel):
    """Роль в списке."""

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    group_id: uuid.UUID
    role: str
    username: str | None = None
    display_name: str | None = None
