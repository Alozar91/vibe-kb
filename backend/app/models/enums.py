"""Перечисления модели данных (data-model.md §3, §4, §6, §13, §5.1)."""


from app.models.base import StrEnum


class MaterialStatus(StrEnum):
    """Статус материала (концепция §6)."""

    DRAFT = "draft"
    ON_REVIEW = "on_review"
    CONFIRMED = "confirmed"
    ARCHIVED = "archived"
    DELETED = "deleted"


class GroupRole(StrEnum):
    """Роль в группе (data-model §3)."""

    READER = "reader"
    EDITOR = "editor"
    REVIEWER = "reviewer"
    OWNER = "owner"


class AttributeType(StrEnum):
    """Тип значений атрибутов (data-model §5.1)."""

    STRING = "string"
    NUMBER = "number"
    DATE = "date"
    BOOL = "bool"
    SELECT = "select"
    MULTI_SELECT = "multi_select"


class TextExtracted(StrEnum):
    """Исход извлечения текста (ЧНК-7)."""

    SUCCESS = "success"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class AvStatus(StrEnum):
    """Статус антивирус-скана — гейт доступа (НФТ-4)."""

    PENDING = "pending"
    CLEAN = "clean"
    INFECTED = "infected"
    SKIPPED_STUB = "skipped_stub"


class JobStep(StrEnum):
    """Шаги пайплайна (data-model §13, концепция §13.2)."""

    AV = "av"
    EXTRACT = "extract"
    CHUNK = "chunk"
    EMBED = "embed"
    PREVIEW = "preview"


class JobStatus(StrEnum):
    """Статус задачи пайплайна."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
