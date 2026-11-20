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
    """Извлечь и проверить Bearer-токен (АУТ-5)."""

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise PermissionDenied("Отсутствует Bearer-токен")
    return verify_token(auth.removeprefix("Bearer ").strip())


DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[Principal, Depends(get_current_principal)]
