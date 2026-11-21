"""Тесты статусов (СТАТ-1..5): машина состояний, append-only журнал, роли переходов."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.common.db import UoW
from app.common.errors import PermissionDenied, StatusTransitionError
from app.domain.groups import roles_service
from app.domain.groups import service as groups_service
from app.domain.materials import service as materials_service
from app.domain.statuses import service
from app.models.enums import MaterialStatus

pytestmark = pytest.mark.usefixtures("users")

TXT = "содержимое документа".encode()


@pytest.fixture
def env(db: Session, users) -> dict:
    """Группа с editor1/reviewer1/reader1 + черновик от editor1."""

    def _uid(sub: str):
        from sqlalchemy import text

        return db.execute(text("SELECT id FROM users WHERE keycloak_sub=:s"), {"s": sub}).scalar_one()

    with UoW(db) as uow:
        root = groups_service.create_group(uow, users["admin"], None, "С", None)
        roles_service.assign_role(uow, users["admin"], root.id, _uid("sub-editor1"), "editor")
        roles_service.assign_role(uow, users["admin"], root.id, _uid("sub-reviewer1"), "reviewer")
        roles_service.assign_role(uow, users["admin"], root.id, _uid("sub-reader1"), "reader")
        m = materials_service.create_material(
            uow, users["editor1"], root.id, "Черновик-док", None, None, None, "v1", TXT, "f.pdf"
        )
    return {"root": root, "material": m}


class TestTransitions:
    def test_draft_to_on_review_by_editor(self, db: Session, users, env) -> None:
        with UoW(db) as uow:
            m = service.transition(uow, users["editor1"], env["material"].id, "on_review")
        assert m.status == MaterialStatus.ON_REVIEW

    def test_draft_to_confirmed_forbidden(self, db: Session, users, env) -> None:
        """СТАТ-2: Черновик→Подтверждён запрещён (приёмка)."""

        with pytest.raises(StatusTransitionError):
            with UoW(db) as uow:
                service.transition(uow, users["editor1"], env["material"].id, "confirmed")

    def test_confirm_requires_reviewer(self, db: Session, users, env) -> None:
        """ПРВ-4/СТАТ: подтверждение — Проверяющий+, Редактору — 403."""

        with UoW(db) as uow:
            service.transition(uow, users["editor1"], env["material"].id, "on_review")
        with pytest.raises(PermissionDenied):
            with UoW(db) as uow:
                service.transition(uow, users["editor1"], env["material"].id, "confirmed")
        with UoW(db) as uow:
            m = service.transition(uow, users["reviewer1"], env["material"].id, "confirmed")
        assert m.status == MaterialStatus.CONFIRMED

    def test_reader_cannot_transition(self, db: Session, users, env) -> None:
        with pytest.raises(PermissionDenied):
            with UoW(db) as uow:
                service.transition(uow, users["reader1"], env["material"].id, "on_review")

    def test_journal_append_only(self, db: Session, users, env) -> None:
        """СТАТ-3: переходы фиксируются в журнале."""

        with UoW(db) as uow:
            service.transition(uow, users["editor1"], env["material"].id, "on_review")
        with UoW(db) as uow:
            service.transition(uow, users["reviewer1"], env["material"].id, "confirmed")
        entries = service.journal(db, users["reader1"], env["material"].id)
        assert [(e["from_status"], e["to_status"]) for e in entries] == [
            ("draft", "on_review"),
            ("on_review", "confirmed"),
        ]

    def test_idempotent_retry_with_request_id(self, db: Session, users, env) -> None:
        """НФТ-9: ретрай с тем же request_id возвращает исходный ответ без второго перехода."""

        rid = __import__("uuid").uuid4()
        with UoW(db) as uow:
            m1 = service.transition(uow, users["editor1"], env["material"].id, "on_review", rid)
        with UoW(db) as uow:
            m2 = service.transition(uow, users["editor1"], env["material"].id, "on_review", rid)
        assert m1.id == m2.id
        # повтор без ключа — 409 (переход недопустим из текущего статуса)
        with pytest.raises(StatusTransitionError):
            with UoW(db) as uow:
                service.transition(uow, users["editor1"], env["material"].id, "on_review")

    def test_archive_from_confirmed(self, db: Session, users, env) -> None:
        with UoW(db) as uow:
            service.transition(uow, users["editor1"], env["material"].id, "on_review")
        with UoW(db) as uow:
            service.transition(uow, users["reviewer1"], env["material"].id, "confirmed")
        with UoW(db) as uow:
            m = service.transition(uow, users["editor1"], env["material"].id, "archived")
        assert m.status == MaterialStatus.ARCHIVED
        # архив терминален (СТАТ-2)
        with pytest.raises(StatusTransitionError):
            with UoW(db) as uow:
                service.transition(uow, users["editor1"], env["material"].id, "draft")
