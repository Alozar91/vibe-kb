"""Engine, session-factory и прагматичный UoW (ADR-0004, code-standards §2.4).

Sync-first: всё синхронно; async не используется в слое БД.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.common.config import get_settings

if TYPE_CHECKING:
    pass


def create_db_engine(db_url: str | None = None) -> Engine:
    """Engine с пулом и тайм-аутами; вызывается из main.py и воркеров."""

    url = db_url or get_settings().db_url
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Фабрика сессий; commit — ответственность UoW/сервиса, не репозитория."""

    return sessionmaker(bind=engine, expire_on_commit=False)


class UoW:
    """Прагматичный UoW (ADR-0004): сессия = транзакция; commit/rollback явные.

    Поддерживает with-семантику: `with UoW(session) as uow:` — commit при выходе
    без исключений, rollback при исключении (используется в api-обработчиках).
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> UoW:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()


@contextmanager
def unit_of_work(factory: sessionmaker[Session]) -> Iterator[UoW]:
    """Контекст для фоновых задач (Celery) и скриптов: открыл → отработал → commit/rollback."""

    session = factory()
    uow = UoW(session)
    try:
        yield uow
        uow.commit()
    except Exception:
        uow.rollback()
        raise
    finally:
        uow.close()
