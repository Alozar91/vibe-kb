"""HTTP-обработчики групп (api-spec §2–3; code-standards §2.1: тонкие, ≤15 строк)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal, get_db
from app.common.db import UoW
from app.common.errors import NotFound, PermissionDenied
from app.common.security.jwt import Principal
from app.domain.groups import roles_service, service
from app.domain.groups.schemas import GroupCreate, GroupMove, GroupNode, GroupOut, GroupUpdate, RoleAssign, RoleOut

router = APIRouter(tags=["groups"])


@router.get("/groups/roots", response_model=list[GroupNode])
def list_roots(
    session: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)
):
    """Корневые группы, видимые пользователю (api-spec §2)."""

    return service.list_roots_visible(session, principal)


@router.get("/groups/{group_id}/children", response_model=list[GroupNode])
def list_children(
    group_id: uuid.UUID,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Дочерние группы с учётом nav-only видимости (ПРВ-2)."""

    service.get_visible_group(session, principal, group_id)  # родитель должен быть виден
    return service.list_children_visible(session, principal, group_id)


@router.get("/groups/{group_id}", response_model=GroupOut)
def get_group(
    group_id: uuid.UUID,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Карточка группы (видимость ПРВ-1/2)."""

    group, nav_only = service.get_visible_group(session, principal, group_id)
    out = GroupOut.model_validate(group)
    out.nav_only = nav_only
    return out


@router.post("/groups/{group_id}/children", response_model=GroupOut, status_code=201)
def create_child(
    group_id: uuid.UUID,
    payload: GroupCreate,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Создание подгруппы (ГРП-4: Владелец родителя)."""

    with UoW(session) as uow:
        group = service.create_group(uow, principal, group_id, payload.name, payload.description)
        return GroupOut.model_validate(group)


@router.post("/groups", response_model=GroupOut, status_code=201)
def create_root(
    payload: GroupCreate,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Создание корневой группы (ПРВ-8: только системный админ)."""

    with UoW(session) as uow:
        group = service.create_group(uow, principal, None, payload.name, payload.description)
        return GroupOut.model_validate(group)


@router.patch("/groups/{group_id}", response_model=GroupOut)
def update_group(
    group_id: uuid.UUID,
    payload: GroupUpdate,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Переименование/описание (ГРП-4)."""

    with UoW(session) as uow:
        group = service.rename_group(uow, principal, group_id, payload.name, payload.description)
        return GroupOut.model_validate(group)


@router.post("/groups/{group_id}/move", response_model=GroupOut)
def move_group(
    group_id: uuid.UUID,
    payload: GroupMove,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Перемещение (ГРП-1 циклы, ГРП-4 права в обеих группах)."""

    with UoW(session) as uow:
        group = service.move_group(uow, principal, group_id, payload.new_parent_id)
        return GroupOut.model_validate(group)


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(
    group_id: uuid.UUID,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Soft-delete пустой группы (ГРП-3/4)."""

    with UoW(session) as uow:
        service.delete_group(uow, principal, group_id)
    return Response(status_code=204)


@router.post("/groups/{group_id}/restore", response_model=GroupOut)
def restore_group(
    group_id: uuid.UUID,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Восстановление (системный админ)."""

    with UoW(session) as uow:
        group = service.restore_group(uow, principal, group_id)
        return GroupOut.model_validate(group)


@router.get("/groups/{group_id}/roles", response_model=list[RoleOut])
def list_roles(
    group_id: uuid.UUID,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Роли группы: прямые + унаследованные (api-spec §3)."""

    return roles_service.list_roles(session, principal, group_id)


@router.put("/groups/{group_id}/roles/{user_id}", response_model=RoleOut)
def assign_role(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: RoleAssign,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Назначение роли (ПРВ-7, идемпотентно)."""

    with UoW(session) as uow:
        result = roles_service.assign_role(uow, principal, group_id, user_id, payload.role)
    return RoleOut(**{k: v for k, v in result.items() if k in RoleOut.model_fields})


@router.delete("/groups/{group_id}/roles/{user_id}", status_code=204)
def revoke_role(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Отзыв роли."""

    with UoW(session) as uow:
        roles_service.revoke_role(uow, principal, group_id, user_id)
    return Response(status_code=204)


class ChunkerSetting(BaseModel):
    name: str
    params: dict = {}


@router.get("/groups/{group_id}/chunker")
def get_chunker_setting(
    group_id: uuid.UUID,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Настройка чанкера группы (ГРП-5; пусто — разрешение уходит вверх, ЧНК-4)."""

    from app.common.authz import is_admin
    from app.models.identity import ChunkerConfig

    if not is_admin(principal):
        raise PermissionDenied("Настройку чанкера выполняет системный администратор (ГРП-5)")
    row = session.query(ChunkerConfig).filter_by(group_id=group_id).first()
    if row is None:
        return {"name": None, "params": {}, "inherited": True}
    return {"name": row.chunker_name, "params": row.params, "inherited": False}


@router.put("/groups/{group_id}/chunker")
def put_chunker_setting(
    group_id: uuid.UUID,
    payload: ChunkerSetting,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Задать/сбросить настройку чанкера (ГРП-5). Изменение → переиндексация поддерева (ЧНК-9)."""

    from app.common.authz import is_admin
    from app.domain.indexing.chunkers import CHUNKERS
    from app.models.identity import ChunkerConfig

    if not is_admin(principal):
        raise PermissionDenied("Настройку чанкера выполняет системный администратор (ГРП-5)")
    # ЧНК-8 превентивно: несуществующий чанкер — отказ (не ждём fallback)
    if payload.name and payload.name not in CHUNKERS:
        raise NotFound(f"Чанкер «{payload.name}» не зарегистрирован")

    row = session.query(ChunkerConfig).filter_by(group_id=group_id).first()
    changed = False
    if row is None and payload.name:
        session.add(ChunkerConfig(group_id=group_id, chunker_name=payload.name, params=payload.params))
        changed = True
    elif row is not None and payload.name:
        if row.chunker_name != payload.name or row.params != payload.params:
            row.chunker_name = payload.name
            row.params = payload.params
            changed = True
    elif row is not None and not payload.name:
        session.delete(row)
        changed = True
    session.commit()

    requeued = 0
    if changed:
        # ЧНК-9: переиндексация поддерева — актуальные версии всех материалов группы и потомков
        from sqlalchemy import text as _sql

        from app.workers.celery_app import run_pipeline_task

        rows = session.execute(
            _sql(
                """
                SELECT v.id::text FROM material_versions v
                JOIN materials m ON m.id = v.material_id
                JOIN groups g ON g.id = m.group_id
                WHERE m.current_version_id = v.id AND NOT m.is_deleted
                  AND (SELECT path FROM groups WHERE id = :gid) @> g.path
                """
            ),
            {"gid": str(group_id)},
        ).fetchall()
        for (vid,) in rows:
            run_pipeline_task.delay(vid)
            requeued += 1
    return {"changed": changed, "reindex_queued": requeued}
