"""Стандартные чанкеры (ЧНК-2) + разрешение по иерархии (ЧНК-4/5).

Все детерминированы: одинаковый вход → одинаковые чанки (приёмка ЧНК-2).
Контракт будущего BaseChunker (ЧНК-3): name, version, chunk(source, params) -> list[Chunk].
"""

from __future__ import annotations

import re
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

DEFAULT_CHUNKER = "recursive"
DEFAULT_PARAMS = {"size": 1500, "overlap": 200}


def resolve_chunker(session: Session, group_id) -> tuple[str, dict]:
    """ЧНК-4/5: настройка самой вложенной группы в цепочке; иначе системный дефолт."""

    row = session.execute(
        text(
            """
            SELECT cc.chunker_name, cc.params
            FROM chunker_configs cc
            JOIN groups anc ON cc.group_id = anc.id
            WHERE anc.path @> (SELECT path FROM groups WHERE id = :gid)
            ORDER BY nlevel(anc.path) DESC
            LIMIT 1
            """
        ),
        {"gid": str(group_id)},
    ).first()
    if row is None:
        srow = session.execute(
            text("SELECT value FROM settings WHERE key = 'default_chunker'")
        ).first()
        if srow is not None:
            v = srow[0]
            return v.get("name", DEFAULT_CHUNKER), v.get("params", DEFAULT_PARAMS)
        return DEFAULT_CHUNKER, dict(DEFAULT_PARAMS)
    return row[0], dict(row[1] or {})


def _by_chars(text: str, params: dict) -> list[dict]:
    """Фиксированный размер + overlap."""

    size = int(params.get("size", 1500))
    step = max(1, size - int(params.get("overlap", 200)))
    return [
        {"text": text[i : i + size], "metadata": {"start": i, "end": min(i + size, len(text))}}
        for i in range(0, max(len(text), 1), step)
        if text[i : i + size].strip()
    ]


def _recursive(text: str, params: dict) -> list[dict]:
    """Рекурсивный: сплит по абзацам → предложения → символам, склейка до size."""

    size = int(params.get("size", 1500))
    chunks: list[str] = []
    current = ""
    for para in re.split(r"\n\s*\n", text):
        if len(current) + len(para) <= size:
            current += ("\n\n" if current else "") + para
            continue
        if current:
            chunks.append(current)
        if len(para) <= size:
            current = para
            continue
        for sent in re.split(r"(?<=[.!?…])\s+", para):
            if len(current) + len(sent) + 1 <= size:
                current += (" " if current else "") + sent
            else:
                if current:
                    chunks.append(current)
                current = sent[:size]
    if current:
        chunks.append(current)
    return [{"text": c, "metadata": {"len": len(c)}} for c in chunks if c.strip()]


def _by_sentences(text: str, params: dict) -> list[dict]:
    """По предложениям/абзацам: абзац → атом."""

    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return [{"text": p, "metadata": {"type": "paragraph"}} for p in paras]


def _parent_child(text: str, params: dict) -> list[dict]:
    """Parent-child (ЧНК-2): крупные родительские + мелкие поисковые с parent_index."""

    parents = _recursive(text, {**params, "size": int(params.get("parent_size", 3000)), "overlap": 200})
    result: list[dict] = []
    for pi, p in enumerate(parents):
        result.append({"text": p["text"], "metadata": {"parent_index": None}, "parent_index": None})
        for c in _recursive(p["text"], {**params, "size": int(params.get("child_size", 400)), "overlap": 50}):
            result.append({"text": c["text"], "metadata": {"parent_index": pi}, "parent_index": pi})
    return result


def _markdown(text: str, params: dict) -> list[dict]:
    """Разметко-ориентированный: секции по заголовкам #/##/###; в метаданных — заголовок."""

    sections: list[tuple[str, str]] = []
    header = ""
    current: list[str] = []
    for line in text.splitlines():
        if re.match(r"^#{1,6}\s", line):
            if current:
                sections.append((header, "\n".join(current)))
            header = line.lstrip("#").strip()
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append((header, "\n".join(current)))
    return [{"text": body, "metadata": {"header": h}} for h, body in sections if body.strip()]


def _tokens(text: str, params: dict) -> list[dict]:
    """Токен-базированный: ~4 символа ≈ токен (без токенизатора — детерминированная оценка)."""

    tps = int(params.get("tokens_per_chunk", 512)) * 4
    return _by_chars(text, {"size": tps, "overlap": int(params.get("overlap_tokens", 64)) * 4})


def _tables(text: str, params: dict) -> list[dict]:
    """Таблично-ориентированный (ЧНК-2): CSV/TSV → группы строк с повторением заголовка."""

    lines = text.splitlines()
    groups = int(params.get("rows_per_chunk", 20))
    if not lines:
        return []
    header, body = lines[0], lines[1:]
    return [
        {
            "text": "\n".join([header] + body[i : i + groups]),
            "metadata": {"sheet": "1", "rows": [i + 2, min(i + groups, len(body)) + 1]},
        }
        for i in range(0, len(body), groups)
        if body[i : i + groups]
    ]


CHUNKERS: dict[str, Callable[[str, dict], list[dict]]] = {
    "chars": _by_chars,
    "recursive": _recursive,
    "sentences": _by_sentences,
    "parent_child": _parent_child,
    "tokens": _tokens,
    "markdown": _markdown,
    "tables": _tables,
}


def run_chunker(name: str, params: dict, text: str) -> tuple[list[dict], str | None]:
    """Выполнить чанкер; неизвестный → дефолт + предупреждение (ЧНК-8).

    Возвращает (чанки, warning) — warning записывается в jobs.error при done.
    """

    if name not in CHUNKERS:
        warning = f"ЧНК-8: чанкер «{name}» не найден, применён дефолт {DEFAULT_CHUNKER}"
        return CHUNKERS[DEFAULT_CHUNKER](text, params), warning
    return CHUNKERS[name](text, params), None
