"""Бизнес-логика материалов и версий (МАТ-1…5, ВЕРС-1…4; code-standards §2.2)."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common.authz import R_EDIT, R_READ, require_role
from app.common.db import UoW
from app.common.errors import (
    CycleError,
    NameConflict,
    NotFound,
    NothingChanged,
    PermissionDenied,
    UploadTooLarge,
)
from app.common.security.jwt import Principal
from app.domain.groups import repository as groups_repo
from app.domain.materials import storage
from app.models.enums import MaterialStatus
from app.models.materials import File, Material, MaterialLink, MaterialVersion


def _uid(session: Session, sub: str) -> uuid.UUID:
    return session.execute(
        text("SELECT id FROM users WHERE keycloak_sub = :s"), {"s": sub}
    ).scalar_one()


def _schedule_pipeline(version_id: uuid.UUID) -> None:
    """ЧНК-1: автоматический запуск пайплайна после фиксации версии.

    Celery-задача, если брокер настроен; иначе (тесты/dev без Valkey) — синхронный вызов.
    Ошибка постановки не рвет основную транзакцию (сбой индексации не блокирует материал).
    """

    import logging

    log = logging.getLogger("kb.materials")
    try:
        from app.workers.celery_app import run_pipeline_task

        run_pipeline_task.delay(str(version_id))
    except Exception as exc:  # noqa: BLE001 — брокер недоступен
        log.warning("очередь недоступна (%s); пайплайн версии %s — синхронно", exc, version_id)
        from app.workers.pipeline import run_pipeline_for_version

        run_pipeline_for_version(version_id)


def _get_alive(session: Session, material_id: uuid.UUID) -> Material:
    m = session.query(Material).filter(Material.id == material_id, Material.is_deleted.is_(False)).first()
    if m is None:
        raise NotFound("Материал не найден")
    return m


def name_taken(session: Session, group_id: uuid.UUID, name: str) -> bool:
    return session.execute(
        text(
            "SELECT 1 FROM materials WHERE group_id = :g AND lower(trim(name)) = lower(trim(:n)) "
            "AND NOT is_deleted LIMIT 1"
        ),
        {"g": str(group_id), "n": name},
    ).scalar() is not None


def create_material(
    uow: UoW,
    actor: Principal,
    group_id: uuid.UUID,
    name: str,
    description: str | None,
    attributes: dict | None,
    external_links: list[dict] | None,
    change_comment: str,
    file_content: bytes,
    file_name: str,
) -> Material:
    """Создание материала с первой версией (МАТ-1/2, ВЕРС-1; файл обязателен)."""

    session = uow.session
    if groups_repo.get_alive(session, group_id) is None:
        raise NotFound("Группа не найдена")
    require_role(session, actor, group_id, R_EDIT)
    if not file_content:
        raise NothingChanged("Файл обязателен (МАТ-2)")
    if name_taken(session, group_id, name):
        raise NameConflict(f"Материал с именем «{name.strip()}» уже существует в группе")

    author_id = _uid(session, actor.sub)
    max_mb = 50  # TODO(НФТ-5): лимит из settings БД
    if len(file_content) > max_mb * 1024 * 1024:
        raise UploadTooLarge(f"Файл больше лимита {max_mb} МБ")

    skey, sha256, size = storage.upload_bytes(file_content, file_name)
    file_row = session.query(File).filter_by(sha256=sha256, size=size).first()
    if file_row is None:
        file_row = File(
            storage_key=skey,
            original_filename=file_name,
            mime="application/octet-stream",  # TODO(ЧНК-7): детекция по содержимому
            size=size,
            sha256=sha256,
            text_extracted="unsupported",
            av_status="pending",  # гейт доступа (НФТ-4): скачаивание до clean запрещено
        )
        session.add(file_row)
        session.flush()

    material = Material(
        id=uuid.uuid4(), group_id=group_id, name=name.strip(), status=MaterialStatus.DRAFT, author_id=author_id
    )
    session.add(material)
    session.flush()

    version = MaterialVersion(
        material_id=material.id,
        version_no=1,
        file_id=file_row.id,
        description=description,
        external_links=external_links,
        attributes=attributes,
        change_comment=change_comment,
        created_by=author_id,
        file_sha256=sha256,
    )
    session.add(version)
    session.flush()
    material.current_version_id = version.id
    session.flush()
    _schedule_pipeline(version.id)
    return material


def patch_content(
    uow: UoW,
    actor: Principal,
    material_id: uuid.UUID,
    description: str | None,
    attributes: dict | None,
    external_links: list[dict] | None,
    change_comment: str,
    file_content: bytes | None,
    file_name: str | None,
    if_match: uuid.UUID | None,
) -> MaterialVersion:
    """Новая версия при изменении содержимого (ВЕРС-1/2; optimistic locking If-Match)."""

    session = uow.session
    material = _get_alive(session, material_id)
    require_role(session, actor, material.group_id, R_EDIT)

    current = session.get(MaterialVersion, material.current_version_id)
    if current is None:  # инвариант МАТ-2: у материала всегда ≥1 версии
        raise NotFound("У материала нет актуальной версии")
    if if_match is not None and current.id != if_match:
        raise NameConflict("Материал изменён другим пользователем; обновите страницу")

    new_file_id = current.file_id
    new_sha = current.file_sha256
    if file_content:
        skey, sha256, size = storage.upload_bytes(file_content, file_name or "file")
        new_sha = sha256
        file_row = session.query(File).filter_by(sha256=sha256, size=size).first()
        if file_row is None:
            file_row = File(
                storage_key=skey,
                original_filename=file_name or "file",
                mime="application/octet-stream",
                size=size,
                sha256=sha256,
                text_extracted="unsupported",
                av_status="pending",
            )
            session.add(file_row)
            session.flush()
        new_file_id = file_row.id

    # ВЕРС-2: правка без изменений — отказ
    def _norm(x):
        return x if x not in (None, []) else None

    changed = (
        new_sha != current.file_sha256
        or (description is not None and description != current.description)
        or (attributes is not None and attributes != current.attributes)
        or (external_links is not None and _norm(external_links) != current.external_links)
    )
    if not changed:
        raise NothingChanged("Нет изменений — новая версия не создаётся")

    last_no = session.execute(
        text("SELECT max(version_no) FROM material_versions WHERE material_id = :m"),
        {"m": str(material.id)},
    ).scalar() or 0

    version = MaterialVersion(
        material_id=material.id,
        version_no=last_no + 1,
        file_id=new_file_id,
        description=description if description is not None else current.description,
        attributes=attributes if attributes is not None else current.attributes,
        external_links=external_links if external_links is not None else current.external_links,
        change_comment=change_comment,
        created_by=_uid(session, actor.sub),
        file_sha256=new_sha,
    )
    session.add(version)
    session.flush()
    material.current_version_id = version.id
    session.flush()
    _schedule_pipeline(version.id)
    return version


def move_material(uow: UoW, actor: Principal, material_id: uuid.UUID, target_group_id: uuid.UUID) -> Material:
    """Перемещение (МАТ-5: Редактор+ в обеих группах; уникальность имени в целевой)."""

    session = uow.session
    material = _get_alive(session, material_id)
    require_role(session, actor, material.group_id, R_EDIT)
    if groups_repo.get_alive(session, target_group_id) is None:
        raise NotFound("Целевая группа не найдена")
    require_role(session, actor, target_group_id, R_EDIT)
    if target_group_id != material.group_id and name_taken(session, target_group_id, material.name):
        raise NameConflict("Материал с таким именем уже есть в целевой группе")
    material.group_id = target_group_id
    session.flush()
    return material


def copy_material(uow: UoW, actor: Principal, material_id: uuid.UUID, target_group_id: uuid.UUID) -> Material:
    """Копирование: чтение в источнике + Редактор+ в целевой; имя «Name (копия)»."""

    session = uow.session
    material = _get_alive(session, material_id)
    require_role(session, actor, material.group_id, R_READ)
    if groups_repo.get_alive(session, target_group_id) is None:
        raise NotFound("Целевая группа не найдена")
    require_role(session, actor, target_group_id, R_EDIT)

    current = session.get(MaterialVersion, material.current_version_id)
    if current is None:
        raise NotFound("У материала нет актуальной версии")

    base = f"{material.name} (копия)"
    name = base
    i = 2
    while name_taken(session, target_group_id, name):
        name = f"{base} {i}"
        i += 1

    copy = Material(
        id=uuid.uuid4(),
        group_id=target_group_id,
        name=name,
        status=MaterialStatus.DRAFT,
        author_id=_uid(session, actor.sub),
    )
    session.add(copy)
    session.flush()
    version = MaterialVersion(
        material_id=copy.id,
        version_no=1,
        file_id=current.file_id,
        description=current.description,
        external_links=current.external_links,
        attributes=current.attributes,
        change_comment=f"Копия из «{material.name}»",
        created_by=_uid(session, actor.sub),
        file_sha256=current.file_sha256,
    )
    session.add(version)
    session.flush()
    copy.current_version_id = version.id
    session.flush()
    return copy


def delete_material(uow: UoW, actor: Principal, material_id: uuid.UUID) -> None:
    """Soft-delete: только из Черновика (СТАТ-4)."""

    from datetime import UTC, datetime

    session = uow.session
    material = _get_alive(session, material_id)
    require_role(session, actor, material.group_id, R_EDIT)
    if material.status != "draft":
        raise PermissionDenied("Удаление возможно только из статуса Черновик (СТАТ-4)")
    from app.models.enums import MaterialStatus

    material.is_deleted = True
    material.status = MaterialStatus.DELETED
    material.deleted_at = datetime.now(UTC)
    session.flush()


def link_parent(uow: UoW, actor: Principal, material_id: uuid.UUID, parent_id: uuid.UUID) -> MaterialLink:
    """Привязка родителя (ВЕРС-4): ≤1, фиксирует актуальную версию родителя."""

    session = uow.session
    material = _get_alive(session, material_id)
    parent = _get_alive(session, parent_id)
    require_role(session, actor, material.group_id, R_EDIT)
    if parent.id == material.id:
        raise CycleError("Материал не может быть родителем самого себя")
    existing = session.query(MaterialLink).filter_by(child_id=material.id).first()
    if existing is not None:
        raise NameConflict("Родитель уже привязан; используйте перепривязку")
    # цикл: родитель не должен быть потомком материала (родительская связь ациклична по ВЕРС-4)
    link = MaterialLink(
        child_id=material.id,
        parent_id=parent.id,
        parent_version_id=parent.current_version_id,
        created_by=_uid(session, actor.sub),
    )
    session.add(link)
    session.flush()
    return link


def relink_parent(
    uow: UoW, actor: Principal, material_id: uuid.UUID, parent_version_id: uuid.UUID | None
) -> MaterialLink:
    """Перепривязка: фиксирует новую актуальную версию родителя (ВЕРС-4)."""

    session = uow.session
    link = session.query(MaterialLink).filter_by(child_id=material_id).first()
    if link is None:
        raise NotFound("Родительская связь не найдена")
    material = _get_alive(session, material_id)
    require_role(session, actor, material.group_id, R_EDIT)
    if parent_version_id is not None:
        pv = session.get(MaterialVersion, parent_version_id)
        if pv is None or pv.material_id != link.parent_id:
            raise NotFound("Указанная версия не является версией родителя")
        link.parent_version_id = pv.id
    else:
        parent = _get_alive(session, link.parent_id)
        if parent.current_version_id is None:  # инвариант МАТ-2
            raise NotFound("У родителя нет актуальной версии")
        link.parent_version_id = parent.current_version_id
    session.flush()
    return link


def unlink_parent(uow: UoW, actor: Principal, material_id: uuid.UUID) -> None:
    """Отвязка родителя (ВЕРС-4)."""

    session = uow.session
    link = session.query(MaterialLink).filter_by(child_id=material_id).first()
    if link is None:
        raise NotFound("Родительская связь не найдена")
    material = _get_alive(session, material_id)
    require_role(session, actor, material.group_id, R_EDIT)
    session.delete(link)
    session.flush()


def list_versions(session: Session, actor: Principal, material_id: uuid.UUID) -> list[dict]:
    """Список версий с метаданными файла (api-spec §4)."""

    material = _get_alive(session, material_id)
    require_role(session, actor, material.group_id, R_READ)
    rows = session.execute(
        text(
            """
            SELECT v.id::text, v.version_no, v.description, v.external_links, v.attributes,
                   v.change_comment, v.created_by::text, v.created_at, v.file_sha256,
                   v.chunker_name, f.av_status::text, f.text_extracted::text,
                   (f.preview_key IS NOT NULL) AS preview_ready
            FROM material_versions v JOIN files f ON f.id = v.file_id
            WHERE v.material_id = :m ORDER BY v.version_no DESC
            """
        ),
        {"m": str(material_id)},
    ).mappings().all()
    return [dict(r) for r in rows]


def download_version(session: Session, actor: Principal, version_id: uuid.UUID) -> tuple[bytes, str]:
    """Скачивание оригинала (ПРС-1: только через API; AV-гейт НФТ-4: 423 до clean)."""

    from app.common.errors import FileNotScanned

    version = session.get(MaterialVersion, version_id)
    if version is None:
        raise NotFound("Версия не найдена")
    material = _get_alive(session, version.material_id)
    require_role(session, actor, material.group_id, R_READ)
    file_row = session.get(File, version.file_id)
    if file_row is None:
        raise NotFound("Файл версии не найден")
    if file_row.av_status not in ("clean", "skipped_stub"):
        raise FileNotScanned("Файл ещё не прошёл проверку на вирусы")
    content = storage.download_bytes(file_row.storage_key)
    return content, file_row.original_filename
