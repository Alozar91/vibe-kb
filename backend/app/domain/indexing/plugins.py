"""Динамическая загрузка чанкеров-плагинов (ЧНК-3): plugins/chunkers/*.py без пересборки.

Контракт плагина (ЧНК-3): модуль с классом Chunker, атрибуты name, version,
метод chunk(source, params) -> list[dict {"text":..., "metadata":...}].
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.domain.indexing.chunkers import CHUNKERS
from app.models.pipeline import ChunkerRegistryEntry

log = logging.getLogger("kb.plugins")

_plugins: dict[str, Any] = {}  # name → (callable, version)


def _plugin_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "plugins" / "chunkers"


def reload_plugins(session: Session) -> list[str]:
    """Перечитать каталог плагинов, обновить реестр (ЧНК-3/8); вернуть имена."""

    loaded: list[str] = []
    for py in sorted(_plugin_dir().glob("*.py")):
        if py.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"kb_plugin_{py.stem}", py)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"не удалось загрузить спецификацию {py.name}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            instance = module.Chunker()
            name = str(instance.name)
            _plugins[name] = (instance.chunk, str(instance.version))
            code_hash = str(hash(py.read_bytes()))
            _upsert_registry(session, name, code_hash, builtin=False, loaded=True, error=None)
            loaded.append(name)
        except Exception as e:  # noqa: BLE001 — ЧНК-8: ошибка плагина не валит систему
            log.warning("плагин %s не загружен: %s", py.name, e)
            _upsert_registry(session, py.stem, None, builtin=False, loaded=False, error=str(e))
    # builtin-чанкеры тоже фиксируем в реестре
    for name in CHUNKERS:
        _upsert_registry(session, name, None, builtin=True, loaded=True, error=None)
    session.commit()
    return loaded


def _upsert_registry(
    session: Session, name: str, code_hash: str | None, builtin: bool, loaded: bool, error: str | None
) -> None:
    row = session.query(ChunkerRegistryEntry).filter_by(name=name).first()
    if row is None:
        session.add(
            ChunkerRegistryEntry(
                name=name, code_hash=code_hash, builtin=builtin, is_loaded=loaded, error=error
            )
        )
    else:
        row.code_hash = code_hash
        row.builtin = builtin
        row.is_loaded = loaded
        row.error = error


def get_plugin_chunker(name: str) -> Any | None:
    """Получить плагинный чанкер (для run_chunker)."""

    return _plugins.get(name)
