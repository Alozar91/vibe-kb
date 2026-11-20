"""Агрегатор роутеров: include_router всех срезов, префикс /api/v1 (code-standards §2.1).

main.py включает только этот агрегатор. Пути — по api-spec.md.
Этап 0: файлы срезов содержат пустые роутеры-заглушки; заполнение — по этапам.
"""

from fastapi import APIRouter

from app.api import admin, groups, materials, notifications, search, statuses

api_router = APIRouter(prefix="/api/v1")


@api_router.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Проверка живости (deployment.md §5, smoke-тест)."""

    return {"status": "ok"}


api_router.include_router(groups.router)
api_router.include_router(materials.router)
api_router.include_router(statuses.router)
api_router.include_router(search.router)
api_router.include_router(notifications.router)
api_router.include_router(admin.router)
