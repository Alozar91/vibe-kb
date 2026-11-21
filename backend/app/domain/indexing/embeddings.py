"""Клиент эмбеддингов: OpenAI-compatible API (РАГ-3; bge-m3 dense 1024)."""

from __future__ import annotations

import hashlib

import httpx

from app.common.config import get_settings


def _post(url: str, payload: dict, api_key: str) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    resp = httpx.post(url, json=payload, headers=headers, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Эмбеддинги текстов (пайплайн, ЧНК/индексация)."""

    s = get_settings()
    if not s.embeddings_base_url:
        raise RuntimeError("KB_EMBEDDINGS_BASE_URL не настроен")
    data = _post(
        f"{s.embeddings_base_url.rstrip('/')}/embeddings",
        {"model": s.embeddings_model, "input": texts},
        s.embeddings_api_key,
    )
    return [item["embedding"] for item in data["data"]]


def embed_query(query: str) -> str:
    """Эмбеддинг запроса для KNN (строка для pgvector: '[1,2,...]')."""

    s = get_settings()
    if not s.embeddings_base_url:
        # Деградация: детерминированный псевдовектор (dev-режим без моделей)
        return _stub_vector(query, s.embeddings_dims)
    data = _post(
        f"{s.embeddings_base_url.rstrip('/')}/embeddings",
        {"model": s.embeddings_model, "input": [query]},
        s.embeddings_api_key,
    )
    vec = data["data"][0]["embedding"]
    return "[" + ",".join(str(x) for x in vec) + "]"


def _stub_vector(text: str, dims: int) -> str:
    """Детерминированный вектор из хэша (только dev/тесты: поиск по векторам без модели)."""

    return "[" + ",".join(f"{v:.6f}" for v in _stub_vector_list(text, dims)) + "]"


def _stub_vector_list(text: str, dims: int) -> list[float]:
    """Список float для ORM-записи (pgvector принимает list)."""

    digest = hashlib.sha256(text.encode()).digest()
    values: list[float] = [b / 255.0 for b in digest[:33]]
    while len(values) < dims:
        digest = hashlib.sha256(digest).digest()
        values.extend(b / 255.0 for b in digest)
    return values[:dims]


def chat_completion(messages: list[dict], max_tokens: int = 1024) -> str:
    """LLM-ответ (RAG with_answer, Этап 2)."""

    s = get_settings()
    base = getattr(s, "llm_base_url", "") or s.embeddings_base_url
    key = getattr(s, "llm_api_key", "") or s.embeddings_api_key
    model = getattr(s, "llm_model", "") or s.embeddings_model
    data = _post(
        f"{base.rstrip('/')}/chat/completions",
        {"model": model, "messages": messages, "max_tokens": max_tokens},
        key,
    )
    return data["choices"][0]["message"]["content"]
