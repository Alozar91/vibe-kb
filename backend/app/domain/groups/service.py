"""Бизнес-логика среза groups (ГРП-1…5, ПРВ-1…8; code-standards §2.2)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common.authz import R_OWN, effective_role, is_admin, require_role
from app.common.db import UoW
from app.common.errors import CycleError, NameConflict, NotFound, PermissionDenied
from app.common.security.jwt import Principal
from app.domain.groups import repository as repo
from app.models.identity import Group


def _build_path(session: Session, parent: Group | None, group_id: uuid.UUID, name: str) -> str:
    """Материализованный путь: slug имени + суффикс id (уникальность сегмента).

    Путь содержит slug (латиница/цифры/подчёркивание) — ltree требует label-синтаксис.
    Нестандартные имена → сегмент 'g' + короткий id.
    """

    import re

    slug = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip())[:50] or "g"
    return f"{slug}.{group_id.hex[:8]}" if parent is None else f"{parent.path}.{slug}.{group_id.hex[:8]}"


def create_group(
    uow: UoW, actor: Principal, parent_id: uuid.UUID | None, name: str, description: str | None
) -> Group:
    """Создание подгруппы (ГРП-4: Владелец родителя; корневые — только админ, ПРВ-8)."""

    session = uow.session

    if parent_id is None:
        if not is_admin(actor):
            raise PermissionDenied("Корневые группы создаёт системный администратор")
        parent = None
    else:
        parent = repo.get_alive(session, parent_id)
        if parent is None:
            raise NotFound("Родительская группа не найдена")
        require_role(session, actor, parent_id, R_OWN)

    if repo.name_taken(session, parent_id, name):
        raise NameConflict(f"Группа с именем «{name.strip()}» уже существует здесь")

    group = Group(
        id=uuid.uuid4(), name=name.strip(), description=description, parent_id=parent_id
    )
    group.path = _build_path(session, parent, group.id, group.name)
    session.add(group)
    session.flush()
    from app.domain.search.indexing import index_group

    index_group(session, group.id)  # ПСК-1: name_tsv/description_tsv
    return group


def rename_group(uow: UoW, actor: Principal, group_id: uuid.UUID, name: str | None, description: str | None) -> Group:
    """Переименование/описание (ГРП-4: Владелец группы)."""

    session = uow.session
    group = repo.get_alive(session, group_id)
    if group is None:
        raise NotFound("Группа не найдена")
    require_role(session, actor, group_id, R_OWN)

    if name is not None and name.strip() != group.name:
        if repo.name_taken(session, group.parent_id, name):
            raise NameConflict(f"Группа с именем «{name.strip()}» уже существует здесь")
        old_path = group.path
        group.name = name.strip()
        # пересчёт path своего сегмента и всех потомков
        parent = session.get(Group, group.parent_id) if group.parent_id else None
        new_path = _build_path(session, parent, group.id, group.name)
        repo.subtree_update_paths(session, group, old_path, new_path)
        group.path = new_path

    if description is not None:
        group.description = description
    session.flush()
    from app.domain.search.indexing import index_group

    index_group(session, group.id)  # ПСК-1: tsv при переименовании/описании
    return group


def move_group(uow: UoW, actor: Principal, group_id: uuid.UUID, new_parent_id: uuid.UUID | None) -> Group:
    """Перемещение группы (ГРП-1: без циклов; ГРП-4: Владелец в обеих группах)."""

    session = uow.session
    group = repo.get_alive(session, group_id)
    if group is None:
        raise NotFound("Группа не найдена")
    require_role(session, actor, group_id, R_OWN)

    new_parent: Group | None = None
    if new_parent_id is not None:
        new_parent = repo.get_alive(session, new_parent_id)
        if new_parent is None:
            raise NotFound("Новая родительская группа не найдена")
        require_role(session, actor, new_parent_id, R_OWN)
        # ГРП-1: цикл = новая родительская внутри поддерева перемещаемой
        q = text("SELECT 1 FROM groups WHERE id = :pid AND path <@ CAST(:gpath AS ltree)")
        if session.execute(q, {"pid": str(new_parent_id), "gpath": group.path}).scalar():
            raise CycleError("Нельзя переместить группу внутрь самой себя")

    if new_parent_id != group.parent_id:
        if new_parent_id is not None and repo.name_taken(session, new_parent_id, group.name):
            raise NameConflict(f"Группа с именем «{group.name}» уже существует в целевой группе")

        old_path = group.path
        group.parent_id = new_parent_id
        session.flush()
        new_path = _build_path(session, new_parent, group.id, group.name)
        repo.subtree_update_paths(session, group, old_path, new_path)
        group.path = new_path
    session.flush()
    return group


def delete_group(uow: UoW, actor: Principal, group_id: uuid.UUID) -> None:
    """Soft-delete пустой группы (ГРП-3: без живых материалов и живых подгрупп; ГРП-4)."""

    session = uow.session
    group = repo.get_alive(session, group_id)
    if group is None:
        raise NotFound("Группа не найдена")
    require_role(session, actor, group_id, R_OWN)

    if repo.has_alive_materials(session, group_id):
        raise PermissionDenied("В группе или поддереве есть материалы — удаление запрещено")
    if repo.has_alive_children(session, group_id):
        raise PermissionDenied("В группе есть живые подгруппы — сначала удалите их")


    group.is_deleted = True
    group.deleted_at = datetime.now(UTC)
    session.flush()


def restore_group(uow: UoW, actor: Principal, group_id: uuid.UUID) -> Group:
    """Восстановление удалённой группы (только системный админ, ГРП-4/api-spec §2)."""

    if not is_admin(actor):
        raise PermissionDenied("Восстановление выполняет системный администратор")
    session = uow.session
    group = repo.get_any(session, group_id)
    if group is None:
        raise NotFound("Группа не найдена")
    if not group.is_deleted:
        raise NotFound("Группа не удалена")

    # имя может быть занято живой группой у того же родителя за время отсутствия
    if repo.name_taken(session, group.parent_id, group.name):
        raise NameConflict("Имя занято живой группой; переименуйте конфликтующую")

    group.is_deleted = False
    group.deleted_at = None
    session.flush()
    return group


def list_children_visible(session: Session, actor: Principal, parent_id: uuid.UUID | None) -> list[Group]:
    """Дети, видимые пользователю (api-spec §2: отфильтровано, nav_only ПРВ-2)."""

    candidates = repo.roots(session) if parent_id is None else repo.children(session, parent_id)
    visible = set(  # идентификаторы групп с полным или nav-доступом
        uuid.UUID(g) for g in visible_ids(session, actor)
    )
    return [g for g in candidates if g.id in visible]


def get_visible_group(session: Session, actor: Principal, group_id: uuid.UUID) -> tuple[Group, bool]:
    """Группа + nav_only-признак. nav_only=True: виден узел, но не содержимое (ПРВ-2).

    Бросает NotFound, если группа не видна вовсе (ПРВ-2: не раскрываем существование).
    """

    group = repo.get_alive(session, group_id)
    if group is None:
        raise NotFound("Группа не найдена")
    role = effective_role(session, actor, group_id)
    if role is not None:
        return group, False
    # роль ниже по поддереву → nav_only (потомок: его path внутри группы)
    q = text(
        """
        SELECT 1 FROM group_roles gr
        JOIN groups dg ON dg.id = gr.group_id
        WHERE gr.user_id = (SELECT id FROM users WHERE keycloak_sub = :sub)
          AND CAST(:gpath AS ltree) @> dg.path
        LIMIT 1
        """
    )
    if session.execute(q, {"sub": actor.sub, "gpath": group.path}).scalar():
        return group, True
    raise NotFound("Группа не найдена")


def visible_ids(session: Session, actor: Principal) -> list[str]:
    """Обёртка над authz.visible_group_ids (импорт наверху запрещён циклом)."""

    from app.common.authz import visible_group_ids

    return visible_group_ids(session, actor)


def list_roots_visible(session: Session, actor: Principal) -> list[Group]:
    """Корневые группы, видимые пользователю."""

    candidates = repo.roots(session)
    visible = set(uuid.UUID(g) for g in visible_ids(session, actor))
    return [g for g in candidates if g.id in visible]
