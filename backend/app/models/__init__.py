"""Импорт всех моделей для Alembic autogenerate (app/models/__init__.py).

Каждый новый модуль моделей добавлять сюда — иначе autogenerate не увидит таблицу.
"""

from app.models.base import AuditMixin, Base, PkMixin, SoftDeleteMixin
from app.models.enums import (
    AttributeType,
    AvStatus,
    GroupRole,
    JobStatus,
    JobStep,
    MaterialStatus,
    TextExtracted,
)
from app.models.identity import Group, User
from app.models.identity import GroupRole as GroupRoleModel
from app.models.materials import AttributeDef, File, Material, MaterialLink, MaterialVersion
from app.models.pipeline import (
    AuditLog,
    Chunk,
    ChunkerRegistryEntry,
    Job,
    NotificationDelivery,
    NotificationEvent,
    NotificationSubscription,
    Setting,
    StatusJournal,
)

__all__ = [
    "AuditMixin",
    "Base",
    "PkMixin",
    "SoftDeleteMixin",
    # enums
    "AttributeType",
    "AvStatus",
    "GroupRole",
    "JobStatus",
    "JobStep",
    "MaterialStatus",
    "TextExtracted",
    # identity
    "User",
    "Group",
    "GroupRoleModel",
    "ChunkerConfig",
    # materials
    "AttributeDef",
    "Material",
    "MaterialVersion",
    "File",
    "MaterialLink",
    # pipeline
    "Chunk",
    "StatusJournal",
    "NotificationEvent",
    "NotificationSubscription",
    "NotificationDelivery",
    "Setting",
    "ChunkerRegistryEntry",
    "Job",
    "AuditLog",
]
