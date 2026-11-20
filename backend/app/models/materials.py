"""Модели: attribute_defs, materials, material_versions, files, material_links (data-model §4–7)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuditMixin, Base, PkMixin
from app.models.enums import AttributeType, AvStatus, MaterialStatus, TextExtracted


def _pg_enum(enum_cls: type, name: str) -> Enum:
    """SA Enum по StrEnum со строковыми значениями; тип в БД создаётся один раз."""

    return Enum(enum_cls, values_callable=lambda e: [i.value for i in e], name=name)


MATERIAL_STATUS_ENUM = _pg_enum(MaterialStatus, "material_status")
ATTRIBUTE_TYPE_ENUM = _pg_enum(AttributeType, "attribute_type")
TEXT_EXTRACTED_ENUM = _pg_enum(TextExtracted, "text_extracted")
AV_STATUS_ENUM = _pg_enum(AvStatus, "av_status")


class AttributeDef(PkMixin, AuditMixin, Base):
    """Системный справочник атрибутов (data-model §5.1, ПСК-1)."""

    __tablename__ = "attribute_defs"

    key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[AttributeType] = mapped_column(ATTRIBUTE_TYPE_ENUM, nullable=False)
    options: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Material(PkMixin, AuditMixin, Base):
    """Материал (data-model §4)."""

    __tablename__ = "materials"

    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[MaterialStatus] = mapped_column(
        MATERIAL_STATUS_ENUM, default=MaterialStatus.DRAFT, server_default="draft", nullable=False
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class MaterialVersion(PkMixin, Base):
    """Версия-снимок (data-model §5): файл + описание + ссылки + атрибуты."""

    __tablename__ = "material_versions"

    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_links: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    change_comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    reviewers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    chunker_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunker_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_sha256: Mapped[str] = mapped_column(Text, nullable=False)


class File(PkMixin, Base):
    """Файл-объект хранилища (data-model §6): дедупликация по (sha256, size)."""

    __tablename__ = "files"

    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    preview_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_extracted: Mapped[TextExtracted] = mapped_column(TEXT_EXTRACTED_ENUM, nullable=False)
    av_status: Mapped[AvStatus] = mapped_column(AV_STATUS_ENUM, nullable=False)

    __table_args__ = (UniqueConstraint("sha256", "size", name="uq_files_sha_size"),)


class MaterialLink(PkMixin, Base):
    """Родительский материал (data-model §7, ВЕРС-4): ≤1 родителя на ребёнка."""

    __tablename__ = "material_links"

    child_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id"), nullable=False
    )
    parent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id"), nullable=False
    )
    parent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("material_versions.id"), nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (UniqueConstraint("child_id", name="uq_material_links_child"),)
