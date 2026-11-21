"""ЕДИНСТВЕННАЯ точка проверки прав (ПРВ-9, концепция §8.3).

Модель прав (ПРВ-1…8):
- роли reader/editor/reviewer/owner выдаются на группу, действуют вниз по дереву (ПРВ-1);
- предки видны только для навигации (nav_only, ПРВ-2);
- нет роли — нет доступа (ПРВ-5); системный админ — минуя проверки;
- при пересечении ролей действует наиболее разрешающая (ПРВ-6);
- владелец выдаёт роли на свою группу и вложенные (ПРВ-7);
- кэш прав в Valkey, инвалидация при смене ролей (ПРВ-9; кэш — оптимизация Этапа 1).
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common.config import get_settings
from app.common.errors import PermissionDenied
from app.common.security.jwt import Principal

ROLE_RANK: dict[str, int] = {"reader": 1, "editor": 2, "reviewer": 3, "owner": 4}

# Матрица прав ПРВ-4: ранг, необходимый для операции
R_READ = 1
R_EDIT = 2
R_REVIEW = 3
R_OWN = 4


def is_admin(principal: Principal) -> bool:
    """Системный администратор (ПРВ-5): realm-роль kb-admin (Keycloak) ИЛИ env KB_ADMIN_SUBS (bootstrap/dev)."""

    if "kb-admin" in principal.realm_roles:
        return True
    subs = {s.strip() for s in get_settings().admin_subs.split(",") if s.strip()}
    return principal.sub in subs


def effective_role(session: Session, principal: Principal, group_id: uuid.UUID) -> str | None:
    """Эффективная роль в группе: максимум по всей цепочке предков (ПРВ-1, ПРВ-6).

    Возвращает None, если прав нет вовсе.
    """

    if is_admin(principal):
        return "owner"
    row = session.execute(
        text(
            """
            SELECT gr.role
            FROM group_roles gr
            JOIN groups g_target ON g_target.id = :gid
            WHERE gr.group_id IN (
                -- сама группа + все предки: предок — это группа, чей path содержит path цели
                SELECT id FROM groups
                WHERE groups.path @> g_target.path
            )
              AND gr.user_id = (SELECT id FROM users WHERE keycloak_sub = :sub)
              AND NOT g_target.is_deleted
            ORDER BY array_position(ARRAY['reader','editor','reviewer','owner']::text[], gr.role::text) DESC
            LIMIT 1
            """
        ),
        {"gid": str(group_id), "sub": principal.sub},
    ).scalar()
    return row


def require_role(
    session: Session, principal: Principal, group_id: uuid.UUID, min_rank: int
) -> str:
    """Проверить ранг роли; нет прав/ранга → PermissionDenied (ПРВ-5, ПРВ-4)."""

    role = effective_role(session, principal, group_id)
    if role is None:
        raise PermissionDenied("Нет доступа к группе")
    if ROLE_RANK[role] < min_rank:
        raise PermissionDenied("Недостаточный уровень роли для операции")
    return role


def can_read_group(session: Session, principal: Principal, group_id: uuid.UUID) -> bool:
    """Видимость группы: есть роль где-либо в поддереве ниже ИЛИ в самой группе.

    Группа видима, если (а) пользователь имеет роль в ней или в любом предке (ПРВ-1),
    или (б) имеет роль в любой из её потомков — тогда группа видна как предок (ПРВ-2, nav_only).
    """

    if is_admin(principal):
        return True
    row = session.execute(
        text(
            """
            SELECT 1
            FROM groups target
            WHERE target.id = :gid AND NOT target.is_deleted
              AND (
                -- роль в группе или предках: полный доступ к содержимому
                -- (предок: anc.path — префикс target.path, оператор @> включает саму группу)
                EXISTS (
                    SELECT 1
                    FROM group_roles gr JOIN groups anc ON anc.id = gr.group_id
                    WHERE gr.user_id = (SELECT id FROM users WHERE keycloak_sub = :sub)
                      AND anc.path @> target.path
                )
                OR
                -- роль в поддереве: группа видна только для навигации (ПРВ-2)
                -- (потомок: его path начинается с target.path)
                EXISTS (
                    SELECT 1
                    FROM group_roles gr JOIN groups desc_g ON desc_g.id = gr.group_id
                    WHERE gr.user_id = (SELECT id FROM users WHERE keycloak_sub = :sub)
                      AND target.path @> desc_g.path
                )
              )
            LIMIT 1
            """
        ),
        {"gid": str(group_id), "sub": principal.sub},
    ).scalar()
    return row is not None


def visible_group_ids(session: Session, principal: Principal) -> list[str]:
    """ID всех видимых групп: с ролью (полный доступ) + их предки (nav_only, ПРВ-2).

    Основа фильтрации дерева/поиска/RAG (ПРВ-9: применяется до выдачи).
    """

    if is_admin(principal):
        rows = session.execute(text("SELECT id::text FROM groups WHERE NOT is_deleted")).fetchall()
        return [r[0] for r in rows]

    rows = session.execute(
        text(
            """
            WITH granted AS (
                SELECT g.id, g.path
                FROM group_roles gr
                JOIN groups g ON g.id = gr.group_id
                WHERE gr.user_id = (SELECT id FROM users WHERE keycloak_sub = :sub)
            ),
            subtree AS (
                -- все группы, к которым есть доступ по иерархии вниз (ПРВ-1):
                -- потомки групп с ролью + сами группы (потомок: его path внутри granted.path)
                SELECT gg.id, gg.path FROM groups gg
                JOIN granted ggg ON ggg.path @> gg.path
            ),
            ancestors AS (
                -- предки групп с ролью: nav_only (ПРВ-2)
                -- (предок: его path содержит granted.path)
                SELECT ga.id, ga.path FROM groups ga
                JOIN granted ggg ON ga.path @> ggg.path
            )
            SELECT id::text FROM subtree
            UNION
            SELECT id::text FROM ancestors
            """
        ),
        {"sub": principal.sub},
    ).fetchall()
    return [r[0] for r in rows]
