"""HTTP-обработчики поиска + RAG (api-spec §5–6; SSE — async по code-standards §2.3).

Sync-сервис работает в threadpool (starlette run_in_threadpool) — async-края без логики.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_principal, get_db
from app.common.security.jwt import Principal
from app.domain.search import rag_service
from app.domain.search import service as search_service
from app.domain.search.schemas import SearchIn, SearchOut

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchOut)
def search(
    payload: SearchIn,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Поиск: fulltext | vector | hybrid | attributes (ПСК-1; права до выдачи, ПСК-4)."""

    hits = search_service.search(session, principal, payload)
    return SearchOut(results=hits, total=len(hits))


@router.post("/rag/query")
async def rag_query(
    payload: dict,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """RAG (РАГ-1): retrieval + генерация; stream=true → SSE (citations/token/done)."""

    question = str(payload.get("question", ""))
    group_ids = payload.get("group_ids")
    top_k = int(payload.get("top_k", 8))

    if payload.get("stream"):
        return StreamingResponse(
            _sse_stream(session, principal, question, group_ids, top_k),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    result = await run_in_threadpool(
        rag_service.answer, session, principal, question, group_ids, top_k
    )
    return result


async def _sse_stream(session: Session, principal: Principal, question: str, group_ids: list[str] | None, top_k: int) -> AsyncIterator[str]:
    """Мост sync-генератора → async SSE (логика в sync-сервисе, ADR-0003)."""

    import asyncio

    gen = rag_service.sse_events(session, principal, question, group_ids, top_k)
    while True:
        try:
            chunk = await asyncio.to_thread(_next_or_none, gen)
        except StopIteration:
            break
        if chunk is None:
            break
        yield chunk


def _next_or_none(gen):
    try:
        return next(gen)
    except StopIteration:
        return None


@router.get("/materials/{material_id}/chunks")
def read_chunks(
    material_id: str,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Чанки актуальной версии (MCP read_chunks; ПРВ-9)."""

    from sqlalchemy import text as _sql

    from app.common.authz import R_READ, require_role

    rows = session.execute(
        _sql(
            """
            SELECT c.chunk_index, c.text, c.chunker_name, v.id::text
            FROM chunks c
            JOIN material_versions v ON v.id = c.version_id
            JOIN materials m ON m.id = c.material_id
            WHERE c.material_id = CAST(:mid AS uuid) AND v.id = m.current_version_id
            ORDER BY c.chunk_index
            """
        ),
        {"mid": material_id},
    ).fetchall()
    if rows:
        # проверка прав по группе материала (ПРВ-9)
        gid = session.execute(
            _sql("SELECT group_id::text FROM materials WHERE id = CAST(:mid AS uuid)"),
            {"mid": material_id},
        ).scalar()
        if gid:
            import uuid as _uuid

            require_role(session, principal, _uuid.UUID(gid), R_READ)
    return [{"chunk_index": r[0], "text": r[1], "chunker": r[2], "version_id": r[3]} for r in rows]


@router.get("/materials/{material_id}/tree-path")
def material_tree_path(
    material_id: str,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Путь группы материала (для MCP list_tree / навигации)."""

    import uuid as _uuid

    from sqlalchemy import text as _sql

    from app.common.authz import R_READ, require_role

    gid = session.execute(
        _sql("SELECT group_id::text FROM materials WHERE id = CAST(:mid AS uuid)"),
        {"mid": material_id},
    ).scalar()
    if not gid:
        return []
    require_role(session, principal, _uuid.UUID(gid), R_READ)
    rows = session.execute(
        _sql(
            """
            SELECT g2.id::text, g2.name FROM groups g1
            JOIN groups g2 ON g1.path @> g2.path
            WHERE g1.id = CAST(:gid AS uuid)
            """
        ),
        {"gid": gid},
    ).fetchall()
    return [{"id": r[0], "name": r[1]} for r in rows]
