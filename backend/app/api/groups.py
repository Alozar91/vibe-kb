"""Обработчики групп (code-standards §2.1). Этап 0: каркас, эндпоинты — Этап 1 (ГРП-1…5)."""

from fastapi import APIRouter

router = APIRouter(prefix="/groups", tags=["groups"])
