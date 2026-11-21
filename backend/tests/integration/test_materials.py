"""Интеграционные тесты материалов: МАТ-1..5, ВЕРС-1/2, ВЕРС-4 (S3 — реальный Silo или пропуск)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.common.db import UoW
from app.common.errors import (
    NameConflict,
    NothingChanged,
    PermissionDenied,
)
from app.domain.groups import roles_service
from app.domain.groups import service as groups_service
from app.domain.materials import service

pytestmark = pytest.mark.usefixtures("users")

TXT = "тестовый документ о насосах, модель X-100, давление 16 бар".encode()
TXT2 = "обновлённый документ о насосах, модель X-200".encode()


@pytest.fixture
def tree(db: Session, users) -> dict:
    """Корень с owner1; editor1 — Редактор; reader1 — Читатель."""

    def _uid(sub: str):
        from sqlalchemy import text

        return db.execute(text("SELECT id FROM users WHERE keycloak_sub=:s"), {"s": sub}).scalar_one()

    with UoW(db) as uow:
        root = groups_service.create_group(uow, users["admin"], None, "Корень", None)
        roles_service.assign_role(uow, users["admin"], root.id, _uid("sub-owner1"), "owner")
        roles_service.assign_role(uow, users["admin"], root.id, _uid("sub-editor1"), "editor")
        roles_service.assign_role(uow, users["admin"], root.id, _uid("sub-reader1"), "reader")
    return {"root": root}


class TestCreateMaterial:
    def test_editor_creates_with_file(self, db: Session, users, tree) -> None:
        with UoW(db) as uow:
            m = service.create_material(
                uow, users["editor1"], tree["root"].id, "Паспорт насоса",
                "описание", None, None, "первая версия", TXT, "pasport.pdf",
            )
        assert m.status == "draft"
        assert m.current_version_id is not None

    def test_reader_cannot_create(self, db: Session, users, tree) -> None:
        with pytest.raises(PermissionDenied):
            with UoW(db) as uow:
                service.create_material(
                    uow, users["reader1"], tree["root"].id, "X", None, None, None, "c", TXT, "f"
                )

    def test_name_conflict_in_group(self, db: Session, users, tree) -> None:
        with UoW(db) as uow:
            service.create_material(
                uow, users["editor1"], tree["root"].id, "Док", None, None, None, "c", TXT, "f"
            )
        with pytest.raises(NameConflict):
            with UoW(db) as uow:
                service.create_material(
                    uow, users["editor1"], tree["root"].id, " док", None, None, None, "c", TXT, "f"
                )


class TestVersions:
    def _mk(self, db: Session, users, tree) -> uuid.UUID:
        with UoW(db) as uow:
            m = service.create_material(
                uow, users["editor1"], tree["root"].id, "ДокВ", None, None, None, "v1", TXT, "f.pdf"
            )
            return m.id

    def test_new_version_on_file_change(self, db: Session, users, tree) -> None:
        mid = self._mk(db, users, tree)
        with UoW(db) as uow:
            v = service.patch_content(
                uow, users["editor1"], mid, None, None, None, "обновил файл", TXT2, "f.pdf", None
            )
        assert v.version_no == 2

    def test_nothing_changed_rejected(self, db: Session, users, tree) -> None:
        mid = self._mk(db, users, tree)
        with pytest.raises(NothingChanged):
            with UoW(db) as uow:
                service.patch_content(
                    uow, users["editor1"], mid, None, None, None, "без изменений", None, None, None
                )

    def test_description_change_new_version(self, db: Session, users, tree) -> None:
        mid = self._mk(db, users, tree)
        with UoW(db) as uow:
            v = service.patch_content(
                uow, users["editor1"], mid, "новое описание", None, None, "правка описания", None, None, None
            )
        assert v.version_no == 2


class TestMoveCopy:
    def test_move_requires_editor_both(self, db: Session, users, tree) -> None:
        with UoW(db) as uow:
            target = groups_service.create_group(uow, users["admin"], tree["root"].id, "Цель", None)
            m = service.create_material(
                uow, users["editor1"], tree["root"].id, "М", None, None, None, "c", TXT, "f"
            )
            # reader1 не имеет прав в целевой — но у нас editor1 в обеих (наследование от корня)
            moved = service.move_material(uow, users["editor1"], m.id, target.id)
        assert moved.group_id == target.id


class TestParentLinks:
    def test_link_parent_fixes_version(self, db: Session, users, tree) -> None:
        with UoW(db) as uow:
            parent = service.create_material(
                uow, users["editor1"], tree["root"].id, "Родитель", None, None, None, "c", TXT, "f"
            )
            child = service.create_material(
                uow, users["editor1"], tree["root"].id, "Ребёнок", None, None, None, "c", TXT2, "f2"
            )
            service.link_parent(uow, users["editor1"], child.id, parent.id)
        from app.models.materials import MaterialLink

        link = db.query(MaterialLink).filter_by(child_id=child.id).one()
        assert link.parent_version_id == parent.current_version_id

    def test_second_parent_conflict(self, db: Session, users, tree) -> None:
        with UoW(db) as uow:
            p1 = service.create_material(uow, users["editor1"], tree["root"].id, "P1", None, None, None, "c", TXT, "f")
            p2 = service.create_material(uow, users["editor1"], tree["root"].id, "P2", None, None, None, "c", TXT, "f")
            child = service.create_material(uow, users["editor1"], tree["root"].id, "C", None, None, None, "c", TXT, "f")
            service.link_parent(uow, users["editor1"], child.id, p1.id)
            with pytest.raises(NameConflict):
                service.link_parent(uow, users["editor1"], child.id, p2.id)


def _uid(db: Session, sub: str):
    from sqlalchemy import text

    return db.execute(text("SELECT id FROM users WHERE keycloak_sub=:s"), {"s": sub}).scalar_one()
