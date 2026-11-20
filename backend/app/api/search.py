"""Обработчики поиска + RAG (ПСК/РАГ, SSE — async по §2.3). Этап 0: каркас."""

from fastapi import APIRouter

router = APIRouter(tags=["search"])
