"""Тесты уведомлений (УВЕД-1..3): справочник, подписки по ролям, идемпотентность доставок."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common.db import UoW
from app.domain.groups import roles_service, service as groups_service
from app.domain.notifications import service
from app.models.pipeline import NotificationDelivery

pytestmark = pytest.mark.usefixtures("users")


@pytest.fixture
def seeded(db: Session) -> None:
    service.seed_events(db)


def _uid(db: Session, sub: str):
    return db.execute(text("SELECT id FROM users WHERE keycloak_sub=:s"), {"s": sub}).scalar_one()


class TestEvents:
    def test_seed_idempotent(self, db: Session, seeded) -> None:
        """НФТ-9: повторный seed не дублирует справочник."""

        service.seed_events(db)
        n = db.execute(text("SELECT count(*) FROM notification_events")).scalar()
        assert n == len(service.BASE_EVENTS)

    def test_base_events_present(self, db: Session, seeded) -> None:
        """УВЕД-3: все 7 базовых событий в справочнике."""

        codes = {r[0] for r in db.execute(text("SELECT code FROM notification_events")).all()}
        assert set(service.BASE_EVENTS and [c for c, _ in service.BASE_EVENTS]) == codes


class TestSubscriptions:
    def test_recipients_by_role(self, db: Session, seeded, users) -> None:
        """УВЕД-2: получатели — носители подписанной роли в группе (наследование вниз)."""

        with UoW(db) as uow:
            root = groups_service.create_group(uow, users["admin"], None, "У", None)
            child = groups_service.create_group(uow, users["admin"], root.id, "Дитя", None)
            roles_service.assign_role(uow, users["admin"], root.id, _uid(db, "sub-reviewer1"), "reviewer")
        # событие в child: Проверяющий root получает (наследование роли вниз)
        recipients = service.recipients_for_event(db, "material.sent_to_review", child.id)
        assert str(_uid(db, "sub-reviewer1")) in [str(r) for r in recipients]


class TestDelivery:
    def test_idempotent_deliveries(self, db: Session, seeded, users) -> None:
        """НФТ-9: повторное событие не создаёт вторую доставку."""

        with UoW(db) as uow:
            root = groups_service.create_group(uow, users["admin"], None, "И", None)
            roles_service.assign_role(uow, users["admin"], root.id, _uid(db, "sub-reviewer1"), "reviewer")
            n1 = service.enqueue_event(uow, "material.sent_to_review", root.id, {})
            n2 = service.enqueue_event(uow, "material.sent_to_review", root.id, {})
        assert n1 == 1
        assert n2 == 0
        rows = db.query(NotificationDelivery).all()
        assert len(rows) == 1

    def test_send_dev_stub(self, db: Session, seeded, users) -> None:
        """УВЕД-1: dev без SMTP — доставка помечается sent (заглушка)."""

        with UoW(db) as uow:
            root = groups_service.create_group(uow, users["admin"], None, "С", None)
            roles_service.assign_role(uow, users["admin"], root.id, _uid(db, "sub-reviewer1"), "reviewer")
            service.enqueue_event(uow, "material.sent_to_review", root.id, {})
        sent = service.send_pending(db)
        assert sent == 1
