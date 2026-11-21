"""RAG API (РАГ-1): retrieval + генерация с цитатами [n]; SSE-стриминг.

Синхронный сервис (ADR-0003); async — только на HTTP-краю (code-standards §2.3).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.common.security.jwt import Principal
from app.domain.indexing.embeddings import chat_completion
from app.domain.search import service as search_service
from app.domain.search.schemas import SearchIn

RAG_SYSTEM_PROMPT = (
    "Ты ассистент по корпоративной базе знаний. Отвечай ТОЛЬКО по приведённым "
    "документам. Каждый факт сопровождай ссылкой на источник [n]. Если ответа "
    "нет в документах — прямо скажи об этом."
)


@dataclass
class Citation:
    """Цитата (РАГ-1): материал, версия, чанк, score, deep-link."""

    n: int
    material_id: str
    material_name: str
    version_id: str
    version_no: int | None
    chunk_index: int | None
    score: float
    text: str

    def link(self) -> str:
        """Deep-link: карточка материала + якорь версии/чанка."""

        base = f"/materials/{self.material_id}"
        if self.version_id:
            return f"{base}?version={self.version_id}&chunk={self.chunk_index}"
        return base

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "material_id": self.material_id,
            "material_name": self.material_name,
            "version_id": self.version_id,
            "version_no": self.version_no,
            "chunk_index": self.chunk_index,
            "score": self.score,
            "link": self.link(),
        }


def retrieve(session: Session, principal: Principal, question: str, group_ids: list[str] | None, top_k: int) -> list[Citation]:
    """Гибридный retrieval с цитатами; права до выдачи (РАГ-1, ПРВ-9)."""

    hits = search_service.search(
        session,
        principal,
        SearchIn(
            query=question,
            mode="hybrid",
            group_ids=[__import__("uuid").UUID(g) for g in group_ids] if group_ids else None,
            top_k=top_k,
        ),
    )
    citations: list[Citation] = []
    for h in hits:
        if h.type != "material" or h.material_id is None:
            continue
        citations.append(
            Citation(
                n=len(citations) + 1,
                material_id=str(h.material_id),
                material_name=h.name,
                version_id=str(h.version_id) if h.version_id else "",
                version_no=None,
                chunk_index=h.chunk_index,
                score=h.score,
                text=h.chunk or "",
            )
        )
    return citations[:top_k]


def build_context(citations: list[Citation]) -> str:
    """Контекст для LLM: [n] текст."""

    return "\n\n".join(f"[{c.n}] ({c.material_name}) {c.text}" for c in citations)


def answer(session: Session, principal: Principal, question: str, group_ids: list[str] | None, top_k: int, llm_messages_extra: list[dict] | None = None) -> dict:
    """Полный RAG-ответ: citations + answer (with_answer) — синхронный сервис."""

    citations = retrieve(session, principal, question, group_ids, top_k)
    answer_text = None
    if citations:
        messages = [
            {"role": "system", "content": RAG_SYSTEM_PROMPT},
            {"role": "user", "content": f"Документы:\n\n{build_context(citations)}\n\nВопрос: {question}"},
        ]
        if llm_messages_extra:
            messages.extend(llm_messages_extra)
        try:
            answer_text = chat_completion(messages)
        except Exception as e:  # noqa: BLE001 — LLM недоступен: retrieval всё равно вернётся
            answer_text = f"LLM недоступен: {e}"
    return {"answer": answer_text, "citations": [c.to_dict() for c in citations]}


def sse_events(session: Session, principal: Principal, question: str, group_ids: list[str] | None, top_k: int):
    """Генератор SSE-событий (РАГ-1): citations → token → done (код-стандарт §2.3: sync-генератор)."""

    citations = retrieve(session, principal, question, group_ids, top_k)
    yield "event: citations\ndata: " + _json_dumps([c.to_dict() for c in citations]) + "\n\n"

    if citations:
        messages = [
            {"role": "system", "content": RAG_SYSTEM_PROMPT},
            {"role": "user", "content": f"Документы:\n\n{build_context(citations)}\n\nВопрос: {question}"},
        ]
        try:
            for token in stream_completion(messages):
                yield "event: token\ndata: " + _json_dumps({"token": token}) + "\n\n"
        except Exception as e:  # noqa: BLE001
            yield "event: token\ndata: " + _json_dumps({"token": f"[LLM недоступен: {e}]"}) + "\n\n"

    yield "event: done\ndata: {}\n\n"


def stream_completion(messages: list[dict]):
    """Потоковые токены LLM (OpenAI-compatible stream=true)."""

    import httpx

    from app.common.config import get_settings

    s = get_settings()
    base = getattr(s, "llm_base_url", "") or s.embeddings_base_url
    key = getattr(s, "llm_api_key", "") or s.embeddings_api_key
    model = getattr(s, "llm_model", "") or s.embeddings_model
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    with httpx.stream(
        "POST",
        f"{base.rstrip('/')}/chat/completions",
        json={"model": model, "messages": messages, "stream": True},
        headers=headers,
        timeout=60.0,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload.strip() == "[DONE]":
                break
            import json

            delta = json.loads(payload).get("choices", [{}])[0].get("delta", {})
            token = delta.get("content")
            if token:
                yield token


def _json_dumps(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
