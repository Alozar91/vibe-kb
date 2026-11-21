"""Репозиторий среза groups: SQL-запросы (code-standards §2.2; без бизнес-логики)."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.identity import Group


def get_alive(session: Session, group_id: uuid.UUID) -> Group | None:
    """Живая группа по id."""

    return session.query(Group).filter(Group.id == group_id, Group.is_deleted.is_(False)).first()


def get_any(session: Session, group_id: uuid.UUID) -> Group | None:
    """Группа по id без фильтра (для restore)."""

    return session.query(Group).filter(Group.id == group_id).first()


def name_taken(session: Session, parent_id: uuid.UUID | None, name: str) -> bool:
    """ГРП-2: имя занято среди живых детей родителя (case-insensitive, trim)."""

    q = text(
        """
        SELECT 1 FROM groups
        WHERE coalesce(parent_id, uuid_nil()) = coalesce(:pid, uuid_nil())
          AND lower(trim(name)) = lower(trim(:name))
          AND NOT is_deleted
        LIMIT 1
        """
    )
    return session.execute(q, {"pid": str(parent_id) if parent_id else None, "name": name}).scalar() is not None


def children(session: Session, parent_id: uuid.UUID) -> list[Group]:
    """Живые дети группы."""

    return (
        session.query(Group)
        .filter(Group.parent_id == parent_id, Group.is_deleted.is_(False))
        .order_by(Group.name)
        .all()
    )


def roots(session: Session) -> list[Group]:
    """Живые корневые группы."""

    return (
        session.query(Group)
        .filter(Group.parent_id.is_(None), Group.is_deleted.is_(False))
        .order_by(Group.name)
        .all()
    )


def has_alive_materials(session: Session, group_id: uuid.UUID) -> bool:
    """ГРП-3: в группе есть не удалённые материалы (в т.ч. в поддереве)."""

    q = text(
        """
        SELECT 1
        FROM materials m
        JOIN groups g ON g.id = m.group_id
        WHERE m.is_deleted = false
          AND (g.id = :gid OR g.path <@ (SELECT path FROM groups WHERE id = :gid))
        LIMIT 1
        """
    )
    return session.execute(q, {"gid": str(group_id)}).scalar() is not None


def has_alive_children(session: Session, group_id: uuid.UUID) -> bool:
    """ГРП-3: есть живые подгруппы."""

    q = text(
        """
        SELECT 1 FROM groups
        WHERE parent_id = :gid AND NOT is_deleted
        LIMIT 1
        """
    )
    return session.execute(q, {"gid": str(group_id)}).scalar() is not None


def subtree_update_paths(
    session: Session, group: Group, old_path: str, new_path: str
) -> None:
    """Пересчёт path поддерева при перемещении (data-model §2): одна операция UPDATE."""

    q = text(
        """
        UPDATE groups
        SET path = :new_path || subpath(path, nlevel(:old_path))
        WHERE path <@ CAST(:old_path AS ltree)
        """
    )
    session.execute(q, {"old_path": old_path, "new_path": new_path})
