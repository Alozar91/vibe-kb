"""Заполнение FTS-колонок при записи (ПСК-1: tsv-колонки + GIN-индексы, data-model §7).

Вызывается сервисами при insert/update: chunks.tsv_ru/tsv_en — из пайплайна (step_chunk),
materials.name_tsv и groups.name_tsv/description_tsv — при создании/переименовании.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session


def index_chunks(session: Session, version_id: uuid.UUID) -> None:
    """tsv чанков версии (russian/english); вызывается после вставки чанков."""

    session.execute(
        text(
            "UPDATE chunks SET tsv_ru = to_tsvector('russian', text),"
            " tsv_en = to_tsvector('english', text) WHERE version_id = :v"
        ),
        {"v": str(version_id)},
    )


def index_material(session: Session, material_id: uuid.UUID) -> None:
    """name_tsv материала (после создания/переименования/копирования)."""

    session.execute(
        text("UPDATE materials SET name_tsv = to_tsvector('russian', name) WHERE id = :m"),
        {"m": str(material_id)},
    )


def index_group(session: Session, group_id: uuid.UUID) -> None:
    """name_tsv + description_tsv группы (после создания/переименования)."""

    session.execute(
        text(
            "UPDATE groups SET name_tsv = to_tsvector('russian', name),"
            " description_tsv = to_tsvector('russian', coalesce(description, '')) WHERE id = :g"
        ),
        {"g": str(group_id)},
    )
