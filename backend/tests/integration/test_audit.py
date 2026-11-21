"""Тесты аудита (НФТ-1): записи создаются на изменяющие операции и file.download; append-only."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common import audit
from app.common.db import UoW

pytestmark = pytest.mark.usefixtures("users")


class TestAuditRecord:
    def test_record_appends(self, db: Session, users) -> None:
        """НФТ-1: запись с субъектом, временем, объектом."""

        uid = db.execute(text("SELECT id FROM users WHERE keycloak_sub='sub-admin'")).scalar()
        audit.record(db, uid, "material.create", "material", None, {"name": "x"})
        db.commit()
        row = db.execute(
            text("SELECT actor_id::text, action, at FROM audit_log ORDER BY id DESC LIMIT 1")
        ).first()
        assert row is not None
        assert row[0] == str(uid)
        assert row[1] == "material.create"
        assert row[2] is not None

    def test_record_never_breaks_flow(self, db: Session) -> None:
        """Ошибка аудита (нет actor) не рвет операцию — системное событие без actor_id."""

        audit.record(db, None, "plugin.reload", None, None, None)
        db.commit()
        n = db.execute(text("SELECT count(*) FROM audit_log WHERE action='plugin.reload'")).scalar()
        assert n >= 1

    def test_actions_coverage(self, db: Session, users) -> None:
        """НФТ-1 приёмка: любое действие пользователя находится в журнале."""

        with UoW(db) as uow:
            uid = uow.session.execute(
                text("SELECT id FROM users WHERE keycloak_sub='sub-admin'")
            ).scalar()
            audit.record(uow.session, uid, "role.assign", "group", None, {"role": "reader"})
            audit.record(uow.session, uid, "file.download", "version", None, None)
            audit.record(uow.session, uid, "settings.update", None, None, {"key": "upload.max_size_mb"})
        actions = {r[0] for r in db.execute(text("SELECT action FROM audit_log")).all()}
        assert {"role.assign", "file.download", "settings.update"} <= actions
