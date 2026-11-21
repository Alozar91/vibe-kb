"""Машина состояний материала как данные (СТАТ-2, концепция §6; code-standards §2.1).

Таблица переходов: из → {в: минимальная роль (ПРВ-4)}.
Все проверки переходов — только через эту таблицу.
"""

from __future__ import annotations

from app.common.authz import R_EDIT, R_REVIEW
from app.models.enums import MaterialStatus as S

# Допустимые переходы (СТАТ-2): from → {to: требуемый ранг роли}
TRANSITIONS: dict[str, dict[str, int]] = {
    S.DRAFT: {
        S.ON_REVIEW: R_EDIT,   # отправить на проверку (Редактор+)
        S.DELETED: R_EDIT,     # soft-delete черновика (СТАТ-4)
    },
    S.ON_REVIEW: {
        S.CONFIRMED: R_REVIEW,  # подтвердить (Проверяющий+, ПРВ-4)
        S.DRAFT: R_EDIT,        # вернуть на доработку
        S.ARCHIVED: R_REVIEW,   # архивировать с проверки
    },
    S.CONFIRMED: {
        S.DRAFT: R_EDIT,        # вернуть в черновик (редактирование)
        S.ARCHIVED: R_EDIT,     # архивировать
    },
    S.ARCHIVED: {},             # архив — терминальный (восстановление — через админа? нет: только из confirmed/draft)
    S.DELETED: {},              # удалён — терминальный
}


def can_transition(from_status: str, to_status: str) -> bool:
    """Переход разрешён таблицей?"""

    return to_status in TRANSITIONS.get(from_status, {})


def required_rank(from_status: str, to_status: str) -> int:
    """Минимальный ранг роли для перехода (ПРВ-4)."""

    return TRANSITIONS.get(from_status, {}).get(to_status, 10**9)  # 10^9 = запрещён
