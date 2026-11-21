"""Интеграционные тесты среза groups (ГРП-1…5) и прав (ПРВ-1…8) — на живой Postgres.

Запуск: pytest tests/integration — требует docker-стенд (compose up postgres).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.common.db import UoW
from app.common.errors import CycleError, NameConflict, NotFound, PermissionDenied
from app.common.security.jwt import Principal
from app.domain.groups import roles_service, service
from app.models.identity import Group

pytestmark = pytest.mark.usefixtures("users")


@pytest.fixture
def root_group(db: Session, users) -> Group:
    """Корневая группа от админа; owner1 — Владелец корня (ПРВ-8: роли выдаёт админ)."""

    with UoW(db) as uow:
        group = service.create_group(uow, users["admin"], None, "Корень", None)
        roles_service.assign_role(
            uow, users["admin"], group.id, _uid(db, "sub-owner1"), "owner"
        )
        return group


class TestCreate:
    def test_admin_creates_root(self, db: Session, users, root_group: Group) -> None:
        assert root_group.parent_id is None
        assert "." in root_group.path

    def test_non_admin_cannot_create_root(self, db: Session, users) -> None:
        with pytest.raises(PermissionDenied):
            with UoW(db) as uow:
                service.create_group(uow, users["owner1"], None, "Корень2", None)

    def test_owner_of_parent_creates_child(self, db: Session, users, root_group: Group) -> None:
        with UoW(db) as uow:
            child = service.create_group(uow, users["owner1"], root_group.id, "Дочерняя", None)
        assert child.parent_id == root_group.id
        assert child.path.startswith(root_group.path)

    def test_editor_cannot_create_child(self, db: Session, users, root_group: Group) -> None:
        with UoW(db) as uow:
            roles_service.assign_role(uow, users["admin"], root_group.id, _uid(db, "sub-editor1"), "editor")
        with pytest.raises(PermissionDenied):
            with UoW(db) as uow:
                service.create_group(uow, users["editor1"], root_group.id, "Дочерняя", None)

    def test_name_conflict(self, db: Session, users, root_group: Group) -> None:
        with UoW(db) as uow:
            service.create_group(uow, users["owner1"], root_group.id, "Отдел", None)
        with pytest.raises(NameConflict):
            with UoW(db) as uow:
                service.create_group(uow, users["owner1"], root_group.id, "отдел ", None)  # trim+case


def _uid(db: Session, sub: str) -> uuid.UUID:
    from sqlalchemy import text

    return db.execute(text("SELECT id FROM users WHERE keycloak_sub=:s"), {"s": sub}).scalar_one()
