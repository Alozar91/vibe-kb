"""Маппинг доменных исключений в problem+json (api-spec §1)."""

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.common.errors import DomainError


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    """Рендер problem+json для доменных исключений."""

    body: dict[str, Any] = {
        "type": f"https://vibe-kb.ru/errors/{exc.error_type}",
        "title": exc.title,
        "status": exc.status_code,
        "detail": exc.detail,
        "instance": str(request.url.path),
    }
    if exc.extra:
        body.update(exc.extra)
    return JSONResponse(status_code=exc.status_code, content=body)


def register_exception_handlers(app: Any) -> None:
    """Регистрация обработчиков в FastAPI-приложении (вызывается из main.py)."""

    app.add_exception_handler(DomainError, domain_error_handler)
