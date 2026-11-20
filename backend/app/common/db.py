"""Engine, session-factory и прагматичный UoW (ADR-0004, code-standards §2.4).

Sync-first: всё синхронно; async не используется в слое БД.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.common.config import get_settings


def create_db_engine(db_url: str | None = None) -> Engine:
    """Engine с пулом и тайм-аутами; вызывается из main.py и воркеров."""

    url = db_url or get_settings().db_url
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Фабрика сессий; commit — ответственность UoW/сервиса, не репозитория."""

    return sessionmaker(bind=engine, expire_on_commit=False)


class UoW:
    """Прагматичный UoW (ADR-0004): сессия = транзакция; commit/rollback явные.

    Сервис принимает UoW (или Session), репозитории — сессию из него.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def close(self) -> None:
        self.session.close()


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
