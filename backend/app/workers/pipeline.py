"""Пайплайн индексации (ЧНК-1): av → extract → chunk → embed → preview.

Celery-задачи — тонкие обёртки над сервисами (code-standards §2.1).
Идемпотентность: jobs (version_id, step) unique (НФТ-9) — шаг переписывает результат.
AV-заглушка (НФТ-4, dev): все файлы → clean; реальный антивирус — Этап 3.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.common.config import get_settings
from app.common.keys import STEPS
from app.models.enums import AvStatus, JobStatus, JobStep, TextExtracted
from app.models.pipeline import Chunk, Job

log = logging.getLogger("kb.pipeline")

# --- Отдельная sync-сессия для воркера (не через app.state) ---


_engine_holder: list[object] = []  # кэш engine воркера (одна на процесс)


def _session_factory():
    engine = _engine_holder[0] if _engine_holder else None
    if engine is None:
        engine = create_engine(get_settings().db_url, pool_pre_ping=True)
        _session_factory._engine = engine
    return sessionmaker(bind=engine, expire_on_commit=False)


def set_session_url(db_url: str) -> None:
    """Переопределить URL воркера (тесты используют kb_test)."""

    _engine_holder.clear()
    _engine_holder.append(create_engine(db_url, pool_pre_ping=True))


def _ensure_job(session, version_id: uuid.UUID, step: str, material_id: uuid.UUID | None) -> Job:
    """Получить/создать строку jobs (ключ version_id+step, НФТ-9)."""

    job = session.query(Job).filter_by(version_id=version_id, step=JobStep(step)).first()
    if job is None:
        job = Job(material_id=material_id, version_id=version_id, step=JobStep(step), status=JobStatus.PENDING)
        session.add(job)
        session.flush()
    return job


def _start(session, job: Job) -> None:
    job.status = JobStatus.RUNNING
    job.updated_at = datetime.now(UTC)
    session.commit()


def _done(session, job: Job) -> None:
    job.status = JobStatus.DONE
    job.error = None
    job.updated_at = datetime.now(UTC)
    session.commit()


def _fail(session, job: Job, error: str) -> None:
    job.status = JobStatus.FAILED
    job.error = error[:2000]
    job.attempts = (job.attempts or 0) + 1
    job.updated_at = datetime.now(UTC)
    session.commit()
    log.error("шаг %s для %s упал: %s", job.step, job.version_id, error)


# --- Шаги пайплайна ---


def step_av(session, version_id: uuid.UUID) -> None:
    """Антивирус-скан (НФТ-4). Заглушка: помечает clean (dev)."""

    from app.models.materials import MaterialVersion

    version = session.get(MaterialVersion, version_id)
    file_row = version and session.get(type(version).__mro__ and __import__("app.models.materials", fromlist=["File"]).File, version.file_id)
    if file_row is None:
        raise RuntimeError("Файл версии не найден")
    # TODO(НФТ-4, Этап 3): интеграция с реальным AV (ClamAV/ICAP); при infected — гейт навсегда
    file_row.av_status = AvStatus.CLEAN
    session.commit()


def step_extract(session, version_id: uuid.UUID) -> None:
    """Извлечение текста из файла (ЧНК-7): pdf/docx/txt → text; mime по содержимому."""

    from app.domain.indexing.extract import extract_text
    from app.models.materials import File, MaterialVersion

    version = session.get(MaterialVersion, version_id)
    file_row = session.get(File, version.file_id)
    try:
        content = __import__("app.domain.materials.storage", fromlist=["download_bytes"]).download_bytes(file_row.storage_key)
        extracted, mime = extract_text(content, file_row.original_filename)
        file_row.text_extracted = TextExtracted.SUCCESS
        file_row.mime = mime
        # текст сохраняем в metadata_ черновой колонке чанков на шаге chunk; здесь — во временную таблицу не пишем
        _store_extracted(session, version_id, extracted)
    except Exception as e:  # noqa: BLE001 — любой сбой извлечения → failed, файл остаётся доступным
        file_row.text_extracted = TextExtracted.FAILED
        raise RuntimeError(f"Извлечение не удалось: {e}") from e
    session.commit()


def _store_extracted(session, version_id: uuid.UUID, text: str) -> None:
    """Извлечённый текст — во временное хранилище (settings-подобная запись; для MVP — redis/valkey нет в тестах: в jobs.error? нет).

    Простейший носитель: таблица settings с key=extract:{version_id} (data-model §11 допускает служебные ключи).
    """

    from app.models.pipeline import Setting

    row = session.get(Setting, f"extract:{version_id}")
    if row is None:
        session.add(Setting(key=f"extract:{version_id}", value={"text": text[:5_000_000]}))
    else:
        row.value = {"text": text[:5_000_000]}
    session.commit()


def _load_extracted(session, version_id: uuid.UUID) -> str:
    from app.models.pipeline import Setting

    row = session.get(Setting, f"extract:{version_id}")
    return row.value.get("text", "") if row else ""


def step_chunk(session, version_id: uuid.UUID) -> None:
    """Чанкование (ЧНК-2/4/5): resolved-чанкер группы, атомарная замена чанков версии."""

    from app.models.materials import Material, MaterialVersion

    version = session.get(MaterialVersion, version_id)
    material = session.get(Material, version.material_id)

    from app.domain.indexing.chunkers import resolve_chunker, run_chunker

    text = _load_extracted(session, version_id)
    chunker_name, params = resolve_chunker(session, material.group_id)
    chunks = run_chunker(chunker_name, params, text)

    # атомарная замена (НФТ-9): delete + insert в одной транзакции
    session.query(Chunk).filter_by(version_id=version_id, chunker_name=chunker_name).delete()
    for i, c in enumerate(chunks):
        session.add(
            Chunk(
                material_id=material.id,
                version_id=version_id,
                chunk_index=i,
                chunker_name=chunker_name,
                chunker_version="1",
                text=c["text"],
                metadata_=c.get("metadata"),
            )
        )
    version.chunker_name = chunker_name
    version.chunker_version = "1"
    session.commit()


def step_embed(session, version_id: uuid.UUID) -> None:
    """Эмбеддинги чанков (РАГ-3): OpenAI-compatible; upsert по chunks.id (НФТ-9)."""

    from app.domain.indexing.embeddings import embed_texts

    chunks = session.query(Chunk).filter_by(version_id=version_id).order_by(Chunk.chunk_index).all()
    if not chunks:
        return  # нет текста (unsupported) — шаг done без работы
    vectors = embed_texts([c.text for c in chunks])
    for c, v in zip(chunks, vectors, strict=True):
        c.embedding = v
    session.commit()


def step_preview(session, version_id: uuid.UUID) -> None:
    """PDF-превью (ПРС-2): через converter-сервис; офисные → PDF, pdf — сам файл, остальное — skip."""

    from app.domain.indexing.preview import generate_preview
    from app.models.materials import File, MaterialVersion

    version = session.get(MaterialVersion, version_id)
    file_row = session.get(File, version.file_id)
    generate_preview(session, file_row)
    session.commit()


# --- Оркестрация ---


def run_pipeline_for_version(version_id: uuid.UUID) -> None:
    """Полный пайплайн версии: шаги последовательно, каждый с jobs-учётом (ЧНК-1)."""

    session = _session_factory()()
    try:
        from app.models.materials import MaterialVersion

        version = session.get(MaterialVersion, version_id)
        if version is None:
            return
        material_id = version.material_id
        for step in STEPS:
            job = _ensure_job(session, version_id, step, material_id)
            _start(session, job)
            try:
                handler = {
                    "av": step_av,
                    "extract": step_extract,
                    "chunk": step_chunk,
                    "embed": step_embed,
                    "preview": step_preview,
                }[step]
                handler(session, version_id)
                _done(session, job)
            except Exception as e:  # noqa: BLE001 — фиксируем в jobs (ЧНК-1: сбой не блокирует скачивание)
                _fail(session, job, str(e))
                break  # следующий шаг без результата предыдущего невозможен
    finally:
        session.close()
