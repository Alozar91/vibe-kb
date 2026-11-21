"""Тесты поиска (ПСК-1..5): FTS ru/en, атрибуты, права, гибрид (вектор — со стабом)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common.db import UoW
from app.domain.groups import roles_service
from app.domain.groups import service as groups_service
from app.domain.materials import service as materials_service
from app.domain.search import service as search_service
from app.domain.search.schemas import SearchFilters, SearchIn

pytestmark = pytest.mark.usefixtures("users")

DOC_PUMPS = "Насосы центробежные моде­ли X-100: давление до 16 бар, производительность 50 м3/ч".encode()
DOC_VALVES = b"Clack valves specification: pressure 25 bar, DN50 flange"


@pytest.fixture
def corpus(db: Session, users) -> dict:
    """Корпус: группа «Насосы» (2 материала), группа «Клапаны» (1), reader1 — права только на «Насосы»."""

    def _uid(sub: str):
        return db.execute(text("SELECT id FROM users WHERE keycloak_sub=:s"), {"s": sub}).scalar_one()

    with UoW(db) as uow:
        root = groups_service.create_group(uow, users["admin"], None, "ПроверочныйКорпус", None)
        pumps_g = groups_service.create_group(uow, users["admin"], root.id, "Насосы", None)
        valves_g = groups_service.create_group(uow, users["admin"], root.id, "Клапаны", None)
        roles_service.assign_role(uow, users["admin"], pumps_g.id, _uid("sub-reader1"), "reader")

        m1 = materials_service.create_material(
            uow, users["admin"], pumps_g.id, "Паспорт насоса X-100", "Технический паспорт",
            {"doc_type": "pasport", "pressure": 16}, None, "v1", DOC_PUMPS, "pumps.pdf",
        )
        m2 = materials_service.create_material(
            uow, users["admin"], valves_g.id, "Спецификация клапанов", "Valves spec",
            {"doc_type": "spec", "pressure": 25}, None, "v1", DOC_VALVES, "valves.pdf",
        )

        # FTS-колонки (сервисно заполняются воркером; для теста — вручную)
        # + тестовый чанк (пайплайн индексации не входит в этот fixture — Этап 1 步 индексации)
        from app.models.pipeline import Chunk

        for m, txt in ((m1, DOC_PUMPS.decode()), (m2, DOC_VALVES.decode())):
            from app.domain.indexing.embeddings import _stub_vector_list

            uow.session.add(
                Chunk(
                    material_id=m.id,
                    version_id=m.current_version_id,
                    chunk_index=0,
                    chunker_name="test",
                    chunker_version="1",
                    text=txt,
                    embedding=_stub_vector_list(txt, 1024),
                )
            )

        uow.session.execute(text(
            "UPDATE chunks SET tsv_ru = to_tsvector('russian', text), tsv_en = to_tsvector('english', text) WHERE version_id IN (SELECT current_version_id FROM materials)"
        ))
        uow.session.execute(text(
            "UPDATE materials SET name_tsv = to_tsvector('russian', name)"
        ))
        uow.session.execute(text(
            "UPDATE groups SET name_tsv = to_tsvector('russian', name), description_tsv = to_tsvector('russian', coalesce(description,''))"
        ))
    return {"root": root, "pumps_g": pumps_g, "valves_g": valves_g, "m1": m1, "m2": m2}


class TestFulltext:
    def test_finds_by_chunk_russian(self, db: Session, users, corpus) -> None:
        hits = search_service.search(db, users["admin"], SearchIn(query="центробежные", mode="fulltext"))
        assert any(h.material_id == corpus["m1"].id for h in hits)

    def test_finds_group_by_name(self, db: Session, users, corpus) -> None:
        """ПСК-2: поиск находит и группу, и материалы."""

        hits = search_service.search(db, users["admin"], SearchIn(query="Насосы", mode="fulltext"))
        types = {h.type for h in hits}
        assert "group" in types

    def test_finds_english(self, db: Session, users, corpus) -> None:
        """ПСК-5: английский запрос находит английский документ."""

        hits = search_service.search(db, users["admin"], SearchIn(query="valves", mode="fulltext"))
        assert any(h.material_id == corpus["m2"].id for h in hits)


class TestRights:
    def test_reader_sees_only_allowed_groups(self, db: Session, users, corpus) -> None:
        """ПСК-4/ПРВ-9: пользователь с правами только на «Насосы» не видит «Клапаны»."""

        hits = search_service.search(db, users["reader1"], SearchIn(query="bar OR бар OR клапан OR насос", mode="fulltext", top_k=50))
        mids = {str(h.material_id) for h in hits if h.material_id}
        assert str(corpus["m1"].id) in mids or len(hits) == 0
        assert str(corpus["m2"].id) not in mids

    def test_no_rights_empty(self, db: Session, users, corpus) -> None:
        hits = search_service.search(db, users["nobody"], SearchIn(query="насос", mode="fulltext"))
        assert hits == []


class TestAttributes:
    def test_filter_by_attribute(self, db: Session, users, corpus) -> None:
        payload = SearchIn(
            mode="attributes",
            filters=SearchFilters(attributes={"pressure": {"gte": 20}}),
        )
        hits = search_service.search(db, users["admin"], payload)
        assert any(h.material_id == corpus["m2"].id for h in hits)
        assert not any(h.material_id == corpus["m1"].id for h in hits)


class TestHybrid:
    def test_hybrid_merges(self, db: Session, users, corpus) -> None:
        """ПСК-1: гибрид объединяет выдачи FTS и векторного (со стаб-вектором)."""

        hits = search_service.search(db, users["admin"], SearchIn(query="давление", mode="hybrid"))
        assert len(hits) >= 1
