"""HTTP-обработчики материалов и версий (api-spec §4; code-standards §2.1)."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal, get_db
from app.common import audit
from app.common.db import UoW
from app.common.idempotency import HEADER as IDEMPOTENCY_HEADER
from app.common.security.jwt import Principal
from app.domain.materials import service
from app.domain.materials.schemas import (
    MaterialLink,
    MaterialLinkUpdate,
    MaterialMove,
    MaterialOut,
    VersionOut,
)

router = APIRouter(tags=["materials"])


def _require_idempotency(idempotency_key: str | None) -> None:
    """НФТ-9: для изменяющих операций файлов ключ обязателен (api-spec §4)."""

    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Заголовок Idempotency-Key обязателен")


@router.post("/groups/{group_id}/materials", response_model=MaterialOut, status_code=201)
def create_material(
    group_id: uuid.UUID,
    name: str = Form(...),
    change_comment: str = Form(...),
    description: str | None = Form(default=None),
    attributes: str | None = Form(default=None),
    external_links: str | None = Form(default=None),
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(default=None, alias=IDEMPOTENCY_HEADER),
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Создание материала: multipart file + поля (МАТ-1/2; Idempotency-Key обязателен)."""

    _require_idempotency(idempotency_key)
    attrs = json.loads(attributes) if attributes else None
    links = json.loads(external_links) if external_links else None
    content = file.file.read()
    with UoW(session) as uow:
        m = service.create_material(
            uow, principal, group_id, name, description, attrs, links, change_comment,
            content, file.filename or "file",
        )
        audit.record(uow.session, _actor_id(uow.session, principal), "material.create",
                     "material", m.id, {"group_id": str(group_id), "name": m.name})
        return MaterialOut.model_validate(m)


@router.get("/materials/{material_id}", response_model=MaterialOut)
def get_material(
    material_id: uuid.UUID,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Карточка материала (Читатель+)."""

    m = service._get_alive(session, material_id)  # noqa: SLF001 — тонкий доступ на чтение
    from app.common.authz import R_READ, require_role

    require_role(session, principal, m.group_id, R_READ)
    return MaterialOut.model_validate(m)


@router.patch("/materials/{material_id}/content", response_model=VersionOut)
def patch_content(
    material_id: uuid.UUID,
    change_comment: str = Form(...),
    description: str | None = Form(default=None),
    attributes: str | None = Form(default=None),
    external_links: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    if_match: uuid.UUID | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias=IDEMPOTENCY_HEADER),
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Новая версия (ВЕРС-1/2; If-Match optimistic locking; Idempotency-Key обязателен)."""

    _require_idempotency(idempotency_key)
    attrs = json.loads(attributes) if attributes else None
    links = json.loads(external_links) if external_links else None
    content = file.file.read() if file and file.filename else None
    with UoW(session) as uow:
        v = service.patch_content(
            uow, principal, material_id, description, attrs, links, change_comment,
            content, file.filename if file else None, if_match,
        )
        audit.record(uow.session, _actor_id(uow.session, principal), "material.version.upload",
                     "material", material_id, {"version_id": str(v.id), "version_no": v.version_no})
        return VersionOut(
            id=v.id, material_id=v.material_id, version_no=v.version_no,
            description=v.description, external_links=list(v.external_links or []),
            attributes=v.attributes, change_comment=v.change_comment,
            created_by=v.created_by, created_at=v.created_at, file_sha256=v.file_sha256,
            chunker_name=v.chunker_name,
        )


@router.delete("/materials/{material_id}", status_code=204)
def delete_material(
    material_id: uuid.UUID,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Soft-delete из Черновика (СТАТ-4)."""

    with UoW(session) as uow:
        service.delete_material(uow, principal, material_id)
        audit.record(uow.session, _actor_id(uow.session, principal), "material.delete", "material", material_id)
    return Response(status_code=204)


@router.post("/materials/{material_id}/move", response_model=MaterialOut)
def move_material(
    material_id: uuid.UUID,
    payload: MaterialMove,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Перемещение (МАТ-5)."""

    with UoW(session) as uow:
        m = service.move_material(uow, principal, material_id, payload.target_group_id)
        return MaterialOut.model_validate(m)


@router.post("/materials/{material_id}/copy", response_model=MaterialOut, status_code=201)
def copy_material(
    material_id: uuid.UUID,
    payload: MaterialMove,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Копирование в другую группу."""

    with UoW(session) as uow:
        m = service.copy_material(uow, principal, material_id, payload.target_group_id)
        return MaterialOut.model_validate(m)


@router.get("/materials/{material_id}/versions", response_model=list[VersionOut])
def list_versions(
    material_id: uuid.UUID,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Список версий с diff-метаданными."""

    rows = service.list_versions(session, principal, material_id)
    return [VersionOut(**r) for r in rows]


@router.get("/versions/{version_id}/file")
def download_file(
    version_id: uuid.UUID,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Скачивание оригинала (ПРС-1; 423 до AV-скана)."""

    from fastapi.responses import Response as FastResponse

    content, filename = service.download_version(session, principal, version_id)
    audit.record(session, _actor_id(session, principal), "file.download", "version", version_id)
    session.commit()
    return FastResponse(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/materials/{material_id}/links", response_model=MaterialLinkUpdate, status_code=201)
def link_parent(
    material_id: uuid.UUID,
    payload: MaterialLink,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Привязка родителя (ВЕРС-4)."""

    with UoW(session) as uow:
        link = service.link_parent(uow, principal, material_id, payload.parent_id)
    return MaterialLinkUpdate(parent_version_id=link.parent_version_id)


@router.patch("/materials/{material_id}/links", response_model=MaterialLinkUpdate)
def relink_parent(
    material_id: uuid.UUID,
    payload: MaterialLinkUpdate,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Перепривязка (фиксирует новую актуальную версию родителя)."""

    with UoW(session) as uow:
        link = service.relink_parent(uow, principal, material_id, payload.parent_version_id)
    return MaterialLinkUpdate(parent_version_id=link.parent_version_id)


@router.delete("/materials/{material_id}/links", status_code=204)
def unlink_parent(
    material_id: uuid.UUID,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Отвязка родителя (ВЕРС-4)."""

    with UoW(session) as uow:
        service.unlink_parent(uow, principal, material_id)
    return Response(status_code=204)


def _actor_id(session: Session, principal: Principal) -> uuid.UUID | None:
    from sqlalchemy import text as _sql

    return session.execute(
        _sql("SELECT id FROM users WHERE keycloak_sub = :s"), {"s": principal.sub}
    ).scalar()
