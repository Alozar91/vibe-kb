"""Сборка FastAPI-приложения: только wiring, без логики (code-standards §2.1)."""

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api import api_router
from app.common.config import get_settings
from app.common.db import create_db_engine, create_session_factory
from app.common.handlers import register_exception_handlers
from app.common.idempotency import IdempotencyMiddleware

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    """Engine/фабрика сессий — в app.state; deps.get_db берёт их оттуда."""

    engine = create_db_engine()
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    yield
    engine.dispose()


app = FastAPI(
    title=settings.app_name,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# CORS для dev (vite dev-server); на стенде nginx same-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Idempotency-Key → кэш ответов (НФТ-9). Клиент Valkey подключается на стенде; в юнит-тестах cache=None → no-op.
app.add_middleware(IdempotencyMiddleware, cache=None)

register_exception_handlers(app)


app.include_router(api_router)
