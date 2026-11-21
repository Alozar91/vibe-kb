"""Бизнес-логика статусов (СТАТ-2..5): переходы + append-only журнал."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common.authz import require_role
from app.common.db import UoW
from app.common.errors import StatusTransitionError
from app.common.security.jwt import Principal
from app.domain.materials import service as materials_service
from app.domain.statuses.transitions import can_transition, required_rank
from app.models.enums import MaterialStatus
from app.models.materials import Material, MaterialVersion
from app.models.pipeline import StatusJournal


def _uid(session: Session, sub: str) -> uuid.UUID:
    return session.execute(text("SELECT id FROM users WHERE keycloak_sub = :s"), {"s": sub}).scalar_one()


def transition(
    uow: UoW,
    actor: Principal,
    material_id: uuid.UUID,
    to_status: str,
    request_id: uuid.UUID | None = None,
) -> Material:
    """Смена статуса (СТАТ-2: таблица переходов; СТАТ-3: append-only журнал; НФТ-9: request_id)."""

    session = uow.session
    material = materials_service._get_alive(session, material_id)  # noqa: SLF001
    from_status = str(material.status)

    # НФТ-9: ретрай с тем же request_id → исходный ответ (до машины состояний);
    # повтор без ключа отсекается машиной состояний ниже
    if request_id is not None:
        existing = session.execute(
            text("SELECT 1 FROM status_journal WHERE request_id = :r LIMIT 1"),
            {"r": str(request_id)},
        ).scalar()
        if existing:
            return material

    if not can_transition(from_status, to_status):
        raise StatusTransitionError(f"Переход {from_status} → {to_status} запрещён")

    rank = required_rank(from_status, to_status)
    require_role(session, actor, material.group_id, rank)

    material.status = MaterialStatus(to_status)
    session.flush()

    # append-only журнал (СТАТ-3)
    entry = StatusJournal(
        material_id=material.id,
        version_id=material.current_version_id,
        from_status=MaterialStatus(from_status),
        to_status=material.status,
        actor_id=_uid(session, actor.sub),
        request_id=request_id,
    )
    session.add(entry)

    # СТАТ-4: синхронность is_deleted со статусом deleted
    if to_status == MaterialStatus.DELETED:
        material.is_deleted = True
        material.deleted_at = datetime.now(UTC)

    # СТАТ-5: при отправке на проверку фиксируем список Проверяющих группы
    if to_status == MaterialStatus.ON_REVIEW:
        reviewer_ids = session.execute(
            text(
                """
                SELECT array_agg(gr.user_id::text)
                FROM group_roles gr
                JOIN groups anc ON anc.path @> (SELECT path FROM groups WHERE id = :gid)
                WHERE gr.role = 'reviewer' AND gr.group_id = anc.id
                """
            ),
            {"gid": str(material.group_id)},
        ).scalar()
        version = session.get(MaterialVersion, material.current_version_id)
        if version is not None:
            version.reviewers = list(reviewer_ids) if reviewer_ids else []

    # подтверждение: кто подтвердил
    if to_status == MaterialStatus.CONFIRMED:
        version = session.get(MaterialVersion, material.current_version_id)
        if version is not None:
            version.confirmed_by = _uid(session, actor.sub)
            version.confirmed_at = datetime.now(UTC)

    # УВЕД-3: события статусов → доставки (идемпотентно, НФТ-9)
    _notify_status_change(session, material, from_status, to_status)

    session.flush()
    return material


def _notify_status_change(session: Session, material: Material, from_status: str, to_status: str) -> None:
    """События УВЕД-3 при переходах статусов; сбой уведомлений не рвет транзакцию."""

    import logging

    code_by_to = {
        "on_review": "material.sent_to_review",
        "confirmed": "material.confirmed",
        "draft": "material.returned_to_draft" if from_status == "on_review" else None,
        "archived": "material.archived",
    }
    code = code_by_to.get(to_status)
    if code is None:
        return
    try:
        from app.domain.notifications import service as notifications

        notifications.enqueue_event(
            _uow_view(session), code, material.group_id, {"material_id": str(material.id)}
        )
    except Exception as e:  # noqa: BLE001 — УВЕД не блокирует СТАТ
        logging.getLogger("kb.statuses").warning("уведомление не создано: %s", e)


def _uow_view(session: Session) -> UoW:
    """Обёртка сессии в UoW-интерфейс для enqueue_event (без повторного commit)."""

    return UoW(session)


def journal(session: Session, actor: Principal, material_id: uuid.UUID) -> list[dict]:
    """История переходов материала (СТАТ-3: журнал append-only, только чтение)."""

    material = materials_service._get_alive(session, material_id)  # noqa: SLF001
    require_role(session, actor, material.group_id, 1)
    rows = session.execute(
        text(
            """
            SELECT j.from_status::text, j.to_status::text, j.created_at, u.username
            FROM status_journal j LEFT JOIN users u ON u.id = j.actor_id
            WHERE j.material_id = :m ORDER BY j.created_at
            """
        ),
        {"m": str(material_id)},
    ).mappings().all()
    return [dict(r) for r in rows]
