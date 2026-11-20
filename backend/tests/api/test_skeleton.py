"""Этап 0: приложение собирается, health отвечает, доменные ошибки → problem+json."""

from fastapi.testclient import TestClient

from app.main import app


def test_app_imports() -> None:
    """Каркас импортируется и содержит агрегатор + health."""

    from app.api import api_router

    assert api_router.prefix == "/api/v1"


def test_health(client: TestClient) -> None:
    """Smoke: /api/v1/health → 200 (deployment.md §5)."""

    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_domain_error_problem_json(client: TestClient) -> None:
    """Доменное исключение → problem+json (api-spec §1)."""

    # Временно добавляем эндпоинт, бросающий NotFound, на отдельном роутере
    from fastapi import APIRouter

    from app.common.errors import NotFound

    probe = APIRouter()

    @probe.get("/probe/404")
    def _probe() -> None:
        raise NotFound("Целевой объект не существует")

    app.include_router(probe)
    resp = client.get("/probe/404")
    assert resp.status_code == 404
    body = resp.json()
    assert body["title"] == "Не найдено"
    assert body["status"] == 404
    assert "detail" in body and "instance" in body
