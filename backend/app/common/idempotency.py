"""Middleware Idempotency-Key + кэш в Valkey (НФТ-9, концепция §13.2).

Правило: изменяющие операции (POST/PATCH/PUT/DELETE) с заголовком Idempotency-Key
кэшируют ответ на KB_IDEMPOTENCY_TTL_HOURS; повтор с тем же ключом → исходный ответ.
Для загрузки файлов ключ строго обязателен (api-spec); проверка — на уровне эндпоинта.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.common.config import get_settings

IDEMPOTENT_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})
HEADER = "Idempotency-Key"


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Кэш «ключ → ответ» в Valkey. Отсутствие клиента — no-op (тесты, health-check)."""

    def __init__(self, app: Any, cache: Any = None) -> None:
        super().__init__(app)
        self._cache = cache  # объект с get/set (redis-совместимый); None → пропускаем

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        key = request.headers.get(HEADER)
        if self._cache is None or key is None or request.method not in IDEMPOTENT_METHODS:
            return await call_next(request)

        cache_key = _cache_key(request, key)
        hit = self._cache.get(cache_key)
        if hit is not None:
            data = json.loads(hit)
            return JSONResponse(status_code=data["status"], content=data["body"])

        response = await call_next(request)
        if 200 <= response.status_code < 500:
            body = b""
            async for chunk in response.body_iterator:  # type: ignore[attr-defined]
                body += chunk
            ttl = get_settings().idempotency_ttl_hours * 3600
            self._cache.set(cache_key, json.dumps({"status": response.status_code, "body": json.loads(body or b"null")}), ex=ttl)
            return Response(content=body, status_code=response.status_code, headers=dict(response.headers))
        return response


def _cache_key(request: Request, key: str) -> str:
    digest = hashlib.sha256(f"{request.method}:{request.url.path}:{key}".encode()).hexdigest()
    return f"idem:{digest}"
