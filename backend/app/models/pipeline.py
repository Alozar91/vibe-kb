"""Модели: chunks, status_journal, notifications, settings, chunker_registry, jobs, audit_log (data-model §8–14)."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PkMixin
from app.models.enums import JobStatus, JobStep, MaterialStatus


def _pg_enum(enum_cls: type, name: str) -> Enum:
    """SA Enum по StrEnum со строковыми значениями."""

    return Enum(enum_cls, values_callable=lambda e: [i.value for i in e], name=name)


STATUS_ENUM = _pg_enum(MaterialStatus, "material_status")
JOB_STEP_ENUM = _pg_enum(JobStep, "job_step")
JOB_STATUS_ENUM = _pg_enum(JobStatus, "job_status")

EMBEDDING_DIMS = 1024  # BAAI/bge-m3 dense (deployment.md §2)


class Chunk(PkMixin, Base):
    """Чанк (data-model §8): текст + FTS + вектор."""

    __tablename__ = "chunks"

    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("material_versions.id"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunker_name: Mapped[str] = mapped_column(Text, nullable=False)
    chunker_version: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    embedding: Mapped[Vector] = mapped_column(Vector(EMBEDDING_DIMS), nullable=False)

    __table_args__ = (
        UniqueConstraint("version_id", "chunk_index", "chunker_name", name="uq_chunks_version_index_chunker"),
    )


class StatusJournal(PkMixin, Base):
    """Журнал переходов статусов (data-model §9): append-only (СТАТ-2/3)."""

    __tablename__ = "status_journal"

    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("material_versions.id"), nullable=False
    )
    from_status: Mapped[MaterialStatus] = mapped_column(STATUS_ENUM, nullable=False)
    to_status: Mapped[MaterialStatus] = mapped_column(STATUS_ENUM, nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class NotificationEvent(PkMixin, Base):
    """Справочник событий уведомлений (УВЕД-3)."""

    __tablename__ = "notification_events"

    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)


class NotificationSubscription(PkMixin, Base):
    """Настройка «событие × роль → канал» (УВЕД-2)."""

    __tablename__ = "notification_subscriptions"

    event_code: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)


class NotificationDelivery(PkMixin, Base):
    """Доставка уведомления (data-model §10, НФТ-9)."""

    __tablename__ = "notification_deliveries"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    recipient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_notification_deliveries_key"),)


class Setting(Base):
    """Настройка системы (data-model §11): в БД, не env; не секреты (НФТ-5)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class ChunkerRegistryEntry(Base):
    """Реестр чанкеров (data-model §12, ЧНК-3/8)."""

    __tablename__ = "chunker_registry"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    code_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    params_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_loaded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Job(PkMixin, Base):
    """Задача пайплайна (data-model §13): прогресс и ошибки; ключ (version_id, step)."""

    __tablename__ = "jobs"

    material_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    step: Mapped[JobStep] = mapped_column(JOB_STEP_ENUM, nullable=False)
    status: Mapped[JobStatus] = mapped_column(JOB_STATUS_ENUM, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (UniqueConstraint("version_id", "step", name="uq_jobs_version_step"),)


class AuditLog(Base):
    """Журнал аудита (data-model §14): append-only; PK bigserial."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    object_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
