"""Модели: users, groups, group_roles (data-model §1–3)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuditMixin, Base, PkMixin
from app.models.enums import GroupRole as GroupRoleEnum
from app.models.types import Ltree

ROLE_ENUM = Enum(
    GroupRoleEnum, values_callable=lambda e: [i.value for i in e], name="group_role"
)


class User(PkMixin, AuditMixin, Base):
    """Пользователь (data-model §1): строки не удаляются (АУТ-4)."""

    __tablename__ = "users"

    keycloak_sub: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_local: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Group(PkMixin, AuditMixin, Base):
    """Группа (data-model §2): иерархия, soft-delete, материализованный path."""

    __tablename__ = "groups"

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    path: Mapped[str] = mapped_column(Ltree, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class GroupRole(PkMixin, Base):
    """Роль пользователя в группе (data-model §3)."""

    __tablename__ = "group_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id"), nullable=False
    )
    role: Mapped[GroupRoleEnum] = mapped_column(ROLE_ENUM, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "group_id", name="uq_group_roles_user_group"),)
