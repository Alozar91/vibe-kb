"""Детерминированные ключи задач пайплайна (НФТ-9, концепция §13.2).

Ключ = (version_id, step); повтор шага переписывает результат, а не дублирует работу.
"""

from typing import Final
from uuid import UUID

STEPS: Final = ("av", "extract", "chunk", "embed", "preview")


def job_key(version_id: UUID, step: str) -> str:
    """Ключ строки jobs: уникален на пару (version_id, step)."""

    if step not in STEPS:
        raise ValueError(f"Неизвестный шаг пайплайна: {step}")
    return f"{version_id}:{step}"


def task_id(version_id: UUID, step: str) -> str:
    """Id Celery-задачи: одинаковый для повторного запуска шага → дубль в брокере отсекается."""

    return f"kb-pipeline-{job_key(version_id, step)}"


def notification_key(event_id: UUID, recipient_id: UUID) -> str:
    """Ключ доставки уведомления (data-model §10): одно письмо на событие/получателя."""

    return f"{event_id}:{recipient_id}"
