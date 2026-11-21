"""Тесты прав: наследование вниз (ПРВ-1), nav_only (ПРВ-2), объединение (ПРВ-6), запрет (ПРВ-5)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.common.authz import effective_role, visible_group_ids
from app.common.db import UoW
from app.domain.groups import roles_service, service
from app.models.identity import Group

pytestmark = pytest.mark.usefixtures("users")


@pytest.fixture
def tree(db: Session, users) -> dict[str, Group]:
    """Корень → Оборудование → Насосы; корень → Клапаны (сценарий приёмки ПРВ-2)."""

    def _uid(sub: str):
        from sqlalchemy import text

        return db.execute(text("SELECT id FROM users WHERE keycloak_sub=:s"), {"s": sub}).scalar_one()

    with UoW(db) as uow:
        root = service.create_group(uow, users["admin"], None, "Корень", None)
        equip = service.create_group(uow, users["admin"], root.id, "Оборудование", None)
        pumps = service.create_group(uow, users["admin"], equip.id, "Насосы", None)
        valves = service.create_group(uow, users["admin"], root.id, "Клапаны", None)
        # reader1 — Читатель на «Насосы» (вложенная группа, ПРВ-7: админ выдаёт)
        roles_service.assign_role(uow, users["admin"], pumps.id, _uid("sub-reader1"), "reader")
    return {"root": root, "equip": equip, "pumps": pumps, "valves": valves}


class TestHierarchy:
    def test_role_inherits_down(self, db: Session, users, tree) -> None:
        """ПРВ-1: роль на группе действует на вложенные."""

        with UoW(db) as uow:
            roles_service.assign_role(uow, users["admin"], tree["equip"].id, _uid(db, "sub-editor1"), "editor")
        assert effective_role(db, users["editor1"], tree["pumps"].id) == "editor"

    def test_effective_role_max_union(self, db: Session, users, tree) -> None:
        """ПРВ-6: editor на родителе + reader на дочерней = editor внутри дочерней."""

        with UoW(db) as uow:
            roles_service.assign_role(uow, users["admin"], tree["equip"].id, _uid(db, "sub-editor1"), "editor")
        assert effective_role(db, users["editor1"], tree["pumps"].id) == "editor"

    def test_no_role_no_access(self, db: Session, users, tree) -> None:
        """ПРВ-5: нет роли — нет доступа."""

        assert effective_role(db, users["nobody"], tree["root"].id) is None

    def test_nav_only_ancestors(self, db: Session, users, tree) -> None:
        """ПРВ-2: право на «Насосы» видит «Оборудование» и «Корень», но не «Клапаны»."""

        visible = visible_group_ids(db, users["reader1"])
        vis = {uuid.UUID(v) for v in visible}
        assert tree["pumps"].id in vis      # есть роль
        assert tree["equip"].id in vis      # предок: nav_only
        assert tree["root"].id in vis       # предок: nav_only
        assert tree["valves"].id not in vis # соседняя ветка: не видна

    def test_get_visible_group_nav_only_flag(self, db: Session, users, tree) -> None:
        """get_visible_group: nav_only=True для предков, False для группы с ролью."""

        g, nav = service.get_visible_group(db, users["reader1"], tree["pumps"].id)
        assert not nav
        g, nav = service.get_visible_group(db, users["reader1"], tree["equip"].id)
        assert nav
        with pytest.raises(NotFound):
            service.get_visible_group(db, users["nobody"], tree["valves"].id)

    def test_admin_sees_everything(self, db: Session, users, tree) -> None:
        """ПРВ-5: админ минуя проверки."""

        vis = {uuid.UUID(v) for v in visible_group_ids(db, users["admin"])}
        assert all(g.id in vis for g in tree.values())


import uuid  # noqa: E402

from app.common.errors import NotFound  # noqa: E402


def _uid(db: Session, sub: str):
    from sqlalchemy import text

    return db.execute(text("SELECT id FROM users WHERE keycloak_sub=:s"), {"s": sub}).scalar_one()
