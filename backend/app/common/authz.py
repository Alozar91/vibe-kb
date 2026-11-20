"""ЕДИНСТВЕННАЯ точка проверки прав (ПРВ-9, code-standards §2.1).

На Этапе 0 — каркас с контрактом; заполнение по иерархии групп — Этап 1 (ПРВ-1…8).
Кэш прав в Valkey — Этап 1.
"""

from dataclasses import dataclass
from typing import Final

from app.common.errors import PermissionDenied
from app.common.security.jwt import Principal


@dataclass(frozen=True)
class Role:
    """Роль пользователя в группе (group_roles.role, data-model §3)."""

    code: str


READER: Final = "reader"
EDITOR: Final = "editor"
REVIEWER: Final = "reviewer"
OWNER: Final = "owner"


def check(principal: Principal, permission: str, group_id: str) -> None:
    """Проверить право principal на действие permission в группе group_id.

    Все вызовы прав из api/deps.py идут сюда (ПРВ-9). Этап 0: пустая реализация
    с явным отказом, чтобы не пропустить незаполненные проверки в коде Этапа 1.
    """

    raise PermissionDenied("Проверка прав будет реализована на Этапе 1 (ПРВ-1…8)")


def has_role(principal: Principal, role: str, group_id: str) -> bool:  # noqa: ARG001
    """Есть ли у пользователя роль в группе (с учётом иерархии, ПРВ-6). Этап 0: False."""

    return False
