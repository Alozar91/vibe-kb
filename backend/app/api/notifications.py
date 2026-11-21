"""HTTP-обработчики уведомлений (api-spec: настройки/события; УВЕД-2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal, get_db
from app.common.authz import is_admin
from app.common.errors import PermissionDenied
from app.common.security.jwt import Principal
from app.domain.notifications import service

router = APIRouter(tags=["notifications"])


class SubscriptionIn(BaseModel):
    event_code: str
    role: str
    channel: str = "email"


@router.get("/notifications/events")
def list_events(
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Справочник событий (УВЕД-3)."""

    rows = session.execute(text("SELECT code, title FROM notification_events ORDER BY code")).all()
    return [{"code": r[0], "title": r[1]} for r in rows]


@router.get("/notifications/subscriptions")
def list_subscriptions(
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Подписки «событие × роль → канал» (УВЕД-2, системная настройка)."""

    rows = session.execute(
        text("SELECT event_code, role, channel FROM notification_subscriptions ORDER BY event_code, role")
    ).all()
    return [{"event_code": r[0], "role": r[1], "channel": r[2]} for r in rows]


@router.post("/notifications/subscriptions", status_code=201)
def add_subscription(
    payload: SubscriptionIn,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Изменение подписок — системный админ (УВЕД-2)."""

    if not is_admin(principal):
        raise PermissionDenied("Настройку подписок выполняет системный администратор")
    service.seed_events(session)
    from app.models.pipeline import NotificationSubscription

    session.add(
        NotificationSubscription(
            event_code=payload.event_code, role=payload.role, channel=payload.channel
        )
    )
    session.commit()
    return {"status": "ok"}
