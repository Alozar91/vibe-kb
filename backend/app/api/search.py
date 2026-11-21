"""HTTP-обработчики поиска + RAG (api-spec §5–6; SSE — async по code-standards §2.3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal, get_db
from app.common.security.jwt import Principal
from app.domain.search import service
from app.domain.search.schemas import SearchIn, SearchOut

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchOut)
def search(
    payload: SearchIn,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Поиск: fulltext | vector | hybrid | attributes (ПСК-1; права до выдачи, ПСК-4)."""

    hits = service.search(session, principal, payload)
    return SearchOut(results=hits, total=len(hits))


@router.post("/rag/query")
def rag_query(
    payload: dict,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """RAG: retrieval + генерация (РАГ-1). Полная реализация — Этап 2; каркас retrieval — уже работает."""

    from app.domain.search.schemas import SearchIn

    search_in = SearchIn(
        query=payload.get("question", ""),
        mode="hybrid",
        group_ids=payload.get("group_ids"),
        top_k=payload.get("top_k", 8),
    )
    hits = service.search(session, principal, search_in)
    citations = [
        {
            "n": i + 1,
            "material_id": str(h.material_id) if h.material_id else None,
            "version_id": str(h.version_id) if h.version_id else None,
            "chunk_index": h.chunk_index,
            "score": h.score,
        }
        for i, h in enumerate(hits)
    ]
    answer = None
    if payload.get("with_answer"):
        from app.domain.indexing.embeddings import chat_completion

        context = "\n\n".join(f"[{i+1}] {h.chunk or h.name}" for i, h in enumerate(hits))
        answer = chat_completion(
            [
                {"role": "system", "content": "Отвечай по документам, цитируй источники [n]."},
                {"role": "user", "content": f"Документы:\n{context}\n\nВопрос: {payload.get('question', '')}"},
            ]
        )
    return {"answer": answer, "citations": citations, "retrieved": [h.model_dump(mode="json") for h in hits]}
