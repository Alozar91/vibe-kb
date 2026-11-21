"""Запуск MCP-сервера: uvicorn app.mcp.main:app --port 8100 (deployment.md §1)."""

from __future__ import annotations

from app.mcp.server import create_mcp_app

app = create_mcp_app()
