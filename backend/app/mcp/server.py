"""MCP-сервер (РАГ-2): Streamable HTTP, официальный Python SDK.

Инструменты: search, list_tree, get_material, read_chunks, read_file, rag_answer —
все под правами пользователя, от имени которого выполнен запрос (токен в заголовке).
Синхронные сервисы вызываются в threadpool (ADR-0003; логика — в срезах).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import Context, FastMCP
from starlette.concurrency import run_in_threadpool

from app.common.db import create_db_engine, create_session_factory
from app.common.security.jwt import verify_token


@dataclass
class SessionCtx:
    """Сессия БД + пользователь для текущего MCP-запроса."""

    session_factory: object
    principal: object


mcp = FastMCP("vibe-kb", host="0.0.0.0", port=8100)


@mcp.tool()
async def search(query: str, mode: str = "hybrid", top_k: int = 20, ctx: Context | None = None) -> dict:
    """Поиск по базе знаний: fulltext | vector | hybrid | attributes (ПСК-1, права запрашивающего)."""

    from app.domain.search import service as search_service
    from app.domain.search.schemas import SearchIn

    def _run():
        with _db_session(ctx) as (session, principal):
            hits = search_service.search(
                session, principal, SearchIn(query=query, mode=mode, top_k=top_k)
            )
            return {"results": [h.model_dump(mode="json") for h in hits], "total": len(hits)}

    return await run_in_threadpool(_run)


@mcp.tool()
async def list_tree(group_id: str | None = None, ctx: Context | None = None) -> dict:
    """Дерево групп, видимых пользователю (ПРВ-2 nav-only учитывается)."""

    from app.domain.groups import service as groups_service

    def _run():
        with _db_session(ctx) as (session, principal):
            if group_id:
                children = groups_service.list_children_visible(session, principal, uuid.UUID(group_id))
            else:
                children = groups_service.list_roots_visible(session, principal)
            return {
                "groups": [
                    {"id": str(g.id), "name": g.name, "nav_only": False}
                    for g in children
                ]
            }

    return await run_in_threadpool(_run)


@mcp.tool()
async def get_material(material_id: str, ctx: Context | None = None) -> dict:
    """Карточка материала: описание, атрибуты, ссылки, версии, статус (Читатель+)."""

    from app.common.authz import R_READ, require_role
    from app.domain.materials import service as materials_service

    def _run():
        with _db_session(ctx) as (session, principal):
            m = materials_service._get_alive(session, uuid.UUID(material_id))  # noqa: SLF001
            require_role(session, principal, m.group_id, R_READ)
            versions = materials_service.list_versions(session, principal, m.id)
            return {
                "id": str(m.id),
                "name": m.name,
                "status": str(m.status),
                "group_id": str(m.group_id),
                "current_version_id": str(m.current_version_id) if m.current_version_id else None,
                "versions": versions,
            }

    return await run_in_threadpool(_run)


@mcp.tool()
async def read_chunks(material_id: str, ctx: Context | None = None) -> dict:
    """Текстовые чанки актуальной версии (Читатель+; для RAG-потребителей)."""

    from sqlalchemy import text as _sql

    from app.common.authz import R_READ, require_role

    def _run():
        with _db_session(ctx) as (session, principal):
            gid = session.execute(
                _sql("SELECT group_id FROM materials WHERE id = CAST(:m AS uuid)"),
                {"m": material_id},
            ).scalar()
            if gid is None:
                return {"error": "материал не найден"}
            require_role(session, principal, gid, R_READ)
            rows = session.execute(
                _sql(
                    """
                    SELECT c.chunk_index, c.text FROM chunks c
                    JOIN material_versions v ON v.id = c.version_id
                    WHERE c.material_id = CAST(:m AS uuid) AND v.id = (SELECT current_version_id FROM materials WHERE id = CAST(:m AS uuid))
                    ORDER BY c.chunk_index
                    """
                ),
                {"m": material_id},
            ).all()
            return {"chunks": [{"index": r[0], "text": r[1]} for r in rows]}

    return await run_in_threadpool(_run)


@mcp.tool()
async def read_file(version_id: str, ctx: Context | None = None) -> dict:
    """Файл версии: метаданные + ссылка на скачивание через API (ПРС-1; AV-гейт НФТ-4)."""

    from app.domain.materials import service as materials_service

    def _run():
        with _db_session(ctx) as (session, principal):
            content, filename = materials_service.download_version(
                session, principal, uuid.UUID(version_id)
            )
            return {
                "filename": filename,
                "size": len(content),
                "download_url": f"/api/v1/versions/{version_id}/file",
            }

    return await run_in_threadpool(_run)


@mcp.tool()
async def rag_answer(question: str, group_ids: list[str] | None = None, top_k: int = 8, ctx: Context | None = None) -> dict:
    """RAG-ответ с цитатами (РАГ-2: тот же ответ, что RAG API с теми же правами)."""

    from app.domain.search import rag_service

    def _run():
        with _db_session(ctx) as (session, principal):
            return rag_service.answer(session, principal, question, group_ids, top_k)

    return await run_in_threadpool(_run)


# --- Вспомогательное: сессия БД + principal из заголовка Authorization ---


@asynccontextmanager
async def _db_session(ctx: Context) -> AsyncIterator[tuple]:
    """Сессия на время вызова инструмента; principal — из Bearer-токена запроса (РАГ-2)."""

    from app.common.errors import PermissionDenied

    request = ctx.request_context.request if ctx and ctx.request_context else None
    auth = (request.headers.get("authorization", "") if request else "")
    if not auth.startswith("Bearer "):
        raise PermissionDenied("MCP: требуется Bearer-токен пользователя")
    principal = verify_token(auth.removeprefix("Bearer ").strip())

    # v1 SDK: фабрика сессий — локальная (per-процесс); прикрепление к app.state — при деплое
    factory = _local_factory()

    session = factory()
    try:
        yield session, principal
    finally:
        session.close()


_local_engine = None


def _local_factory():
    global _local_engine
    if _local_engine is None:
        from app.common.config import get_settings

        _local_engine = create_db_engine(get_settings().db_url)
    return create_session_factory(_local_engine)


def create_mcp_app():
    """ASGI-приложение MCP (mount в uvicorn mcp-сервиса, deployment.md §1)."""

    return mcp.streamable_http_app()
