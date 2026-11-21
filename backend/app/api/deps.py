"""Общие зависимости обработчиков (code-standards §2.1): пользователь, сессия БД, authz.

Этап 0: сессия БД и извлечение Principal из JWT; маппинг Principal → users и
кэш прав — Этап 1.
"""

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.common.errors import PermissionDenied
from app.common.security.jwt import Principal, verify_token


def get_db(request: Request) -> Generator[Session, None, None]:
    """Сессия БД на время запроса; commit/rollback — в сервисе через UoW (ADR-0004)."""

    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def get_current_principal(request: Request) -> Principal:
    """Извлечь и проверить Bearer-токен (АУТ-5) + синхронизация users (АУТ-4: sub = UUID Keycloak)."""

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise PermissionDenied("Отсутствует Bearer-токен")
    principal = verify_token(auth.removeprefix("Bearer ").strip())
    _sync_user(request.app.state.session_factory, principal)
    return principal


def _sync_user(session_factory, principal: Principal) -> None:
    """upsert users по keycloak_sub (строки не удаляются, АУТ-4; поля обновляются при входе)."""

    from app.models.identity import User

    session = session_factory()
    try:
        user = session.query(User).filter_by(keycloak_sub=principal.sub).first()
        if user is None:
            session.add(
                User(
                    keycloak_sub=principal.sub,
                    username=principal.username,
                    display_name=principal.display_name,
                    email=principal.email,
                    is_local=True,
                )
            )
        else:
            user.username = principal.username
            user.display_name = principal.display_name
            user.email = principal.email
        session.commit()
    except Exception:  # noqa: BLE001 — синхронизация не рвет запрос
        session.rollback()
    finally:
        session.close()


DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[Principal, Depends(get_current_principal)]
