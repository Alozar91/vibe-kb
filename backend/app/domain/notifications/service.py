"""Уведомления (УВЕД-1..3): события × роли → каналы; доставка через очередь, email.

Идемпотентность (НФТ-9): notification_deliveries unique (idempotency_key) — одно письмо
на событие/получателя; ретрай доставки не дублирует.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common.db import UoW
from app.common.errors import NotFound
from app.common.keys import notification_key
from app.models.pipeline import NotificationDelivery, NotificationEvent, NotificationSubscription

# Базовые события (УВЕД-3): справочник, засеивается при первом запуске
BASE_EVENTS: list[tuple[str, str]] = [
    ("material.created", "Материал создан"),
    ("material.sent_to_review", "Материал отправлен на проверку"),
    ("material.confirmed", "Материал подтверждён"),
    ("material.returned_to_draft", "Материал возвращён на доработку"),
    ("material.archived", "Материал отправлен в архив"),
    ("role.changed", "Выданы/изменены права"),
    ("parent.updated", "Родительский материал обновился"),
]

# Подписки по умолчанию (УВЕД-2): событие → роли → канал email
DEFAULT_SUBSCRIPTIONS: list[tuple[str, str, str]] = [
    ("material.sent_to_review", "reviewer", "email"),
    ("material.confirmed", "editor", "email"),
    ("material.returned_to_draft", "editor", "email"),
    ("role.changed", "owner", "email"),
    ("parent.updated", "editor", "email"),
]


def seed_events(session: Session) -> None:
    """Засеять справочник событий и дефолтные подписки (idempotent, НФТ-9)."""

    for code, title in BASE_EVENTS:
        if session.query(NotificationEvent).filter_by(code=code).first() is None:
            session.add(NotificationEvent(code=code, title=title))
    for event_code, role, channel in DEFAULT_SUBSCRIPTIONS:
        if (
            session.query(NotificationSubscription)
            .filter_by(event_code=event_code, role=role, channel=channel)
            .first()
            is None
        ):
            session.add(NotificationSubscription(event_code=event_code, role=role, channel=channel))
    session.commit()


def recipients_for_event(session: Session, code: str, group_id: uuid.UUID) -> list[uuid.UUID]:
    """Получатели события: пользователи с подписанными ролями в группе и её предках (УВЕД-2, ПРВ-1)."""

    rows = session.execute(
        text(
            """
            SELECT DISTINCT gr.user_id::text
            FROM notification_subscriptions ns
            JOIN group_roles gr ON gr.role::text = ns.role
            JOIN groups anc ON anc.id = gr.group_id
            WHERE ns.event_code = :code
              AND anc.path @> (SELECT path FROM groups WHERE id = :gid)
              AND anc.id = gr.group_id
            """
        ),
        {"code": code, "gid": str(group_id)},
    ).fetchall()
    return [uuid.UUID(r[0]) for r in rows]


def enqueue_event(uow: UoW, code: str, group_id: uuid.UUID, payload: dict) -> int:
    """Создать доставки события (idempotent); вернуть число новых. Отправка — Celery-задачей."""

    session = uow.session
    event = session.query(NotificationEvent).filter_by(code=code).first()
    if event is None:
        raise NotFound(f"Неизвестное событие: {code}")
    created = 0
    for recipient in recipients_for_event(session, code, group_id):
        key = notification_key(event.id, recipient)
        if session.query(NotificationDelivery).filter_by(idempotency_key=key).first() is not None:
            continue  # НФТ-9: повторное событие не дублирует доставку
        session.add(
            NotificationDelivery(
                event_id=event.id,
                recipient_id=recipient,
                channel="email",
                status="pending",
                idempotency_key=key,
            )
        )
        created += 1
    session.flush()
    return created


def send_pending(session: Session) -> int:
    """Доставка pending-писем через абстракцию канала (УВЕД-1); SMTP — env-секреты."""

    pending = session.query(NotificationDelivery).filter_by(status="pending").limit(50).all()
    sent = 0
    for d in pending:
        ok = _send_via_channel(session, d)
        d.status = "sent" if ok else "failed"
        if ok:
            d.sent_at = datetime.now(UTC)
            sent += 1
    session.commit()
    return sent


def _send_via_channel(session: Session, delivery: NotificationDelivery) -> bool:
    """Абстракция канала (УВЕД-1): email сейчас; расширение — без переделки."""

    from app.common.config import get_settings

    s = get_settings()
    smtp_host = getattr(s, "smtp_host", "")
    if not smtp_host:
        # dev без SMTP: считаем доставленной (заглушка), креденшелы не в БД
        return True
    try:
        import smtplib
        from email.message import EmailMessage

        event = session.get(NotificationEvent, delivery.event_id)
        if event is None:
            return False
        recipient_email = session.execute(
            text("SELECT email FROM users WHERE id = :u"), {"u": str(delivery.recipient_id)}
        ).scalar()
        if not recipient_email:
            return False
        msg = EmailMessage()
        msg["Subject"] = f"[База знаний] {event.title}"
        msg["From"] = getattr(s, "smtp_from", "noreply@localhost")
        msg["To"] = recipient_email
        msg.set_content(f"Событие: {event.title} ({event.code})")
        with smtplib.SMTP(smtp_host, int(getattr(s, "smtp_port", 25)), timeout=10) as smtp:
            smtp.send_message(msg)
        return True
    except Exception:  # noqa: BLE001 — любой сбой SMTP → failed (ретрай реконсилятором)
        return False
