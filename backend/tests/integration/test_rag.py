"""Тесты RAG (РАГ-1) и фасетов (ПСК-3): retrieval с цитатами, права, deep-link, SSE-события."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from app.common.db import UoW
from app.domain.groups import roles_service
from app.domain.groups import service as groups_service
from app.domain.materials import service as materials_service
from app.domain.search import rag_service
from app.domain.search import service as search_service
from app.domain.search.schemas import SearchIn

pytestmark = pytest.mark.usefixtures("users")

DOC = "Регламент обслуживания насосов: ежемесячная проверка давления, ежеквартальная смазка подшипников".encode()


@pytest.fixture
def corpus(db: Session, users) -> dict:
    def _uid(sub: str):
        return db.execute(text("SELECT id FROM users WHERE keycloak_sub=:s"), {"s": sub}).scalar_one()

    from sqlalchemy import text

    from app.domain.indexing.embeddings import _stub_vector_list
    from app.models.pipeline import Chunk

    with UoW(db) as uow:
        root = groups_service.create_group(uow, users["admin"], None, "Регламенты", None)
        pumps = groups_service.create_group(uow, users["admin"], root.id, "Насосы", None)
        roles_service.assign_role(uow, users["admin"], pumps.id, _uid("sub-reader1"), "reader")
        m = materials_service.create_material(
            uow, users["admin"], pumps.id, "Регламент ТО насосов", "Документ",
            {"doc_type": "reglament"}, None, "v1", DOC, "reglament.pdf",
        )
        uow.session.add(Chunk(
            material_id=m.id, version_id=m.current_version_id, chunk_index=0,
            chunker_name="test", chunker_version="1", text=DOC.decode(),
            embedding=_stub_vector_list(DOC.decode(), 1024),
        ))
        uow.session.execute(text("UPDATE chunks SET tsv_ru=to_tsvector('russian', text), tsv_en=to_tsvector('english', text)"))
        uow.session.execute(text("UPDATE materials SET name_tsv=to_tsvector('russian', name)"))
    return {"root": root, "pumps": pumps, "m": m}


class TestRetrieval:
    def test_citations_with_deeplink(self, db: Session, users, corpus) -> None:
        """РАГ-1 приёмка: цитаты ведут к конкретным версиям (deep-link)."""

        citations = rag_service.retrieve(db, users["admin"], "смазка подшипников", None, 5)
        assert len(citations) >= 1
        c = citations[0]
        assert c.material_id == str(corpus["m"].id)
        assert c.version_id == str(corpus["m"].current_version_id)
        d = c.to_dict()
        assert "link" in d and "/materials/" in d["link"]

    def test_no_rights_empty(self, db: Session, users, corpus) -> None:
        """РАГ-1 приёмка: пользователь без прав — пустой результат."""

        citations = rag_service.retrieve(db, users["nobody"], "смазка", None, 5)
        assert citations == []

    def test_answer_without_llm_returns_citations(self, db: Session, users, corpus) -> None:
        """РАГ-1: LLM недоступен (нет KB_LLM_BASE_URL) — citations всё равно возвращаются."""

        result = rag_service.answer(db, users["admin"], "давление", None, 5)
        assert result["citations"], "цитаты обязательны даже без LLM"
        assert result["answer"] is None or "LLM" in str(result["answer"])


class TestSse:
    def test_sse_events_format(self, db: Session, users, corpus) -> None:
        """РАГ-1: SSE — события citations → done (без LLM token-событий нет)."""

        events = list(rag_service.sse_events(db, users["admin"], "смазка", None, 5))
        kinds = [e.split("\n")[0] for e in events]
        assert kinds[0] == "event: citations"
        assert kinds[-1] == "event: done"
        # citations-событие содержит валидный JSON с цитатами
        data_line = events[0].split("\n")[1]
        assert data_line.startswith("data: ")
        parsed = json.loads(data_line[6:])
        assert isinstance(parsed, list) and len(parsed) >= 1


class TestFacets:
    def test_facets_in_search_out(self, db: Session, users, corpus) -> None:
        """ПСК-3: фасеты по статусу/группе/атрибутам агрегированы на выдаче."""

        hits = search_service.search(db, users["admin"], SearchIn(query="насос", mode="fulltext", top_k=50))
        # фасеты считаются сервисом поверх выдачи
        from app.domain.search.facets import build_facets

        facets = build_facets(db, users["admin"], hits)
        assert "status" in facets and "group" in facets
        status_counts = {f["value"]: f["count"] for f in facets["status"]}
        assert status_counts.get("draft", 0) >= 1


def _text_import():
    from sqlalchemy import text  # noqa: F401
