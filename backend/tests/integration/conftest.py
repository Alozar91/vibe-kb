"""Фикстуры интеграционных тестов: живой Postgres (docker-compose.dev), изолированная схема.

БД доступна на localhost:5432 (KB_TEST_DB_URL переопределяет, по умолчанию — dev-стенд).
Каждый тест получает чистую БД: create_all/drop_all на каждый тест (схема маленькая — быстро).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.common.security.jwt import Principal
from app.models import Base

TEST_DB_URL = os.environ.get(
    "KB_TEST_DB_URL", "postgresql+psycopg://kb:kb@localhost:5433/kb_test"
)

# Инфраструктура тестового стенда (docker-compose.test.yml): порты наружу
os.environ.setdefault("KB_S3_ENDPOINT", "http://localhost:9010")
os.environ.setdefault("KB_S3_ACCESS_KEY", "kbadmin")
os.environ.setdefault("KB_S3_SECRET_KEY", "kbadmin123")
os.environ.setdefault("KB_VALKEY_URL", "redis://localhost:6380/0")
os.environ.setdefault("KB_EMBEDDINGS_BASE_URL", "")

# Тестовый админ (ПРВ-5/8) до первого вызова get_settings (lru_cache)
os.environ.setdefault("KB_ADMIN_SUBS", "sub-admin")
from app.common.config import get_settings as _get_settings  # noqa: E402

_get_settings.cache_clear()


@pytest.fixture(scope="session")
def engine():
    """Engine тестовой БД; база создаётся при отсутствии."""

    admin = create_engine(TEST_DB_URL.rsplit("/", 1)[0] + "/kb", isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        exists = c.execute(text("SELECT 1 FROM pg_database WHERE datname='kb_test'")).scalar()
        if not exists:
            c.execute(text("CREATE DATABASE kb_test"))
    admin.dispose()
    e = create_engine(TEST_DB_URL)
    yield e
    e.dispose()


@pytest.fixture
def db(engine) -> Iterator[Session]:
    """Расширения → чистая схема на каждый тест → сессия."""

    with engine.connect() as c:
        c.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        c.execute(text("CREATE EXTENSION IF NOT EXISTS ltree"))
        c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        c.commit()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def client(db) -> Iterator[TestClient]:
    """TestClient с подменённой фабрикой сессий на тестовую БД."""

    from app.main import app

    factory = sessionmaker(bind=db.bind)
    app.state.session_factory = factory
    with TestClient(app) as c:
        yield c


# --- Принципалы (keycloak_sub); пользователи создаются в БД фикстурой users ---


def make_principal(sub: str, username: str = "") -> Principal:
    return Principal(sub=sub, username=username or sub, display_name=username or sub, email=None, is_local=True)


@pytest.fixture
def users(db) -> dict[str, Principal]:
    """Тестовые пользователи: admin, owner1, editor1, reader1, nobody + строки в БД."""

    from app.models.identity import User

    subs = {
        "admin": "sub-admin",
        "owner1": "sub-owner1",
        "editor1": "sub-editor1",
        "reviewer1": "sub-reviewer1",
        "reader1": "sub-reader1",
        "nobody": "sub-nobody",
    }
    for name, sub in subs.items():
        db.add(
            User(
                keycloak_sub=sub,
                username=name,
                display_name=name,
                email=f"{name}@test.local",
                is_local=True,
                is_blocked=False,
            )
        )
    db.commit()
    return {name: make_principal(sub, name) for name, sub in subs.items()}
