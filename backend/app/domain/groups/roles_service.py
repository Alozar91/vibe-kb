"""Роли в группах (ПРВ-3/4/7, УВЕД-событие при выдаче; api-spec §3)."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common.authz import R_OWN, ROLE_RANK, is_admin, require_role
from app.common.db import UoW
from app.common.errors import NotFound, PermissionDenied
from app.common.security.jwt import Principal
from app.domain.groups import repository as repo
from app.models.enums import GroupRole as GroupRoleEnum
from app.models.identity import GroupRole, User


def list_roles(session: Session, actor: Principal, group_id: uuid.UUID) -> list[dict]:
    """Назначенные роли группы + эффективные, унаследованные сверху (api-spec §3)."""

    require_role(session, actor, group_id, R_OWN)
    direct = session.execute(
        text(
            """
            SELECT gr.user_id::text, gr.group_id::text, gr.role::text, u.username, u.display_name
            FROM group_roles gr JOIN users u ON u.id = gr.user_id
            WHERE gr.group_id = :gid
            ORDER BY u.username
            """
        ),
        {"gid": str(group_id)},
    ).fetchall()
    inherited = session.execute(
        text(
            """
            SELECT gr.user_id::text, anc.id::text AS group_id, gr.role::text, u.username, u.display_name
            FROM group_roles gr
            JOIN users u ON u.id = gr.user_id
            JOIN groups g ON g.id = :gid
            JOIN groups anc ON anc.id = gr.group_id AND anc.path @> g.path AND anc.id != :gid
            ORDER BY u.username
            """
        ),
        {"gid": str(group_id)},
    ).fetchall()

    def _rows(rows) -> list[dict]:
        return [
            {
                "user_id": r[0],
                "group_id": r[1],
                "role": r[2],
                "username": r[3],
                "display_name": r[4],
            }
            for r in rows
        ]

    return _rows(direct) + _rows(inherited)


def assign_role(uow: UoW, actor: Principal, group_id: uuid.UUID, user_id: uuid.UUID, role: str) -> dict:
    """Назначение роли (ПРВ-7: Владелец группы или вложенной; админ). Идемпотентен."""

    session = uow.session
    group = repo.get_alive(session, group_id)
    if group is None:
        raise NotFound("Группа не найдена")

    if not is_admin(actor):
        # Владелец этой группы или любого её предка (ПРВ-7)
        q = text(
            """
            SELECT 1 FROM group_roles gr
            JOIN groups g ON g.id = :gid
            JOIN groups anc ON anc.id = gr.group_id AND anc.path @> g.path
            WHERE gr.user_id = (SELECT id FROM users WHERE keycloak_sub = :sub)
              AND gr.role = 'owner'
            LIMIT 1
            """
        )
        if not session.execute(q, {"gid": str(group_id), "sub": actor.sub}).scalar():
            raise PermissionDenied("Выдачу ролей выполняет Владелец группы или её предка")

    user = session.get(User, user_id)
    if user is None:
        raise NotFound("Пользователь не найден")

    existing = session.query(GroupRole).filter_by(user_id=user_id, group_id=group_id).first()
    if existing is not None:
        if existing.role == role:
            return {"user_id": str(user_id), "group_id": str(group_id), "role": role, "unchanged": True}
        existing.role = GroupRoleEnum(role)
    else:
        session.add(GroupRole(user_id=user_id, group_id=group_id, role=GroupRoleEnum(role)))
    session.flush()

    # TODO(УВЕД-3): событие «выданы права» + инвалидация кэша прав (ПРВ-9) — на шаге уведомлений
    return {"user_id": str(user_id), "group_id": str(group_id), "role": role, "unchanged": False}


def revoke_role(uow: UoW, actor: Principal, group_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Отзыв роли (Владелец+, админ)."""

    session = uow.session
    if repo.get_alive(session, group_id) is None:
        raise NotFound("Группа не найдена")
    if not is_admin(actor):
        q = text(
            """
            SELECT 1 FROM group_roles gr
            JOIN groups g ON g.id = :gid
            JOIN groups anc ON anc.id = gr.group_id AND anc.path @> g.path
            WHERE gr.user_id = (SELECT id FROM users WHERE keycloak_sub = :sub)
              AND gr.role = 'owner'
            LIMIT 1
            """
        )
        if not session.execute(q, {"gid": str(group_id), "sub": actor.sub}).scalar():
            raise PermissionDenied("Отзыв ролей выполняет Владелец группы или её предка")

    existing = session.query(GroupRole).filter_by(user_id=user_id, group_id=group_id).first()
    if existing is None:
        raise NotFound("Роль не назначена")
    session.delete(existing)
    session.flush()


def rank_of(role: str) -> int:
    """Ранг роли (для проверок ПРВ-4)."""

    return ROLE_RANK[role]
