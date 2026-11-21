"""Аудит (НФТ-1): append-only журнал всех изменяющих операций и доступа к файлам.

Записи не редактируются и не удаляются через API; на уровне БД — запрет
UPDATE/DELETE правами приложения (миграция даёт GRANT только INSERT/SELECT).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.pipeline import AuditLog

# Действия (коды): изменяющие операции + доступ к файлам + админ
ACTIONS = {
    "group.create", "group.update", "group.move", "group.delete", "group.restore",
    "role.assign", "role.revoke",
    "material.create", "material.version.upload", "material.delete",
    "material.move", "material.copy", "material.link", "material.unlink",
    "status.change",
    "file.download", "plugin.reload", "settings.update", "reindex.start",
}


def record(
    session: Session,
    actor_id: uuid.UUID | None,
    action: str,
    object_type: str | None = None,
    object_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
    request_id: uuid.UUID | None = None,
) -> None:
    """Запись в журнал (append-only). Ошибка аудита не рвет основную операцию."""

    try:
        session.add(
            AuditLog(
                at=datetime.now(UTC),
                actor_id=actor_id,
                action=action,
                object_type=object_type,
                object_id=object_id,
                details=details,
                request_id=request_id,
            )
        )
        session.flush()
    except Exception:  # noqa: BLE001 — НФТ-1 не должен ломать бизнес-операцию
        import logging

        logging.getLogger("kb.audit").warning("аудит-запись не создана", exc_info=True)
