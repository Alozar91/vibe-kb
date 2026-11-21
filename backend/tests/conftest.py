"""Фикстуры тестов: TestClient с заглушкой engine (Этап 0 — без БД)."""

import os

# Тестовый админ (ПРВ-5/8) — до первого get_settings (lru_cache)
os.environ.setdefault("KB_ADMIN_SUBS", "sub-admin")

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """TestClient без реального engine: startup подключён, но БД не трогаем.

    _wire_engine создаёт engine с дефолтным URL — psycopg не подключается лениво,
    поэтому создание безопасно; соединения в тестах Этапа 0 не открываются.
    """

    with TestClient(app) as c:
        yield c
