"""Административные обработчики (ПРВ-8, ЧНК-8, системные настройки). Этап 0: каркас."""

from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["admin"])
