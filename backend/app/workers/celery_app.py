"""Celery-приложение и задачи (deployment.md §1: worker + beat; очередь Valkey)."""

from __future__ import annotations

import uuid

from celery import Celery
from celery.schedules import crontab

from app.common.config import get_settings

settings = get_settings()

celery_app = Celery(
    "vibe-kb",
    broker=settings.valkey_url,
    backend=settings.valkey_url,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_default_queue="kb",
)

celery_app.conf.beat_schedule = {
    "reconcile-stuck-jobs": {
        "task": "kb.reconcile_jobs",
        "schedule": 300.0,  # 5 мин (§13.1, deployment §4)
    },
    "cleanup-idempotency": {
        "task": "kb.cleanup_idempotency",
        "schedule": crontab(minute=0),  # 1 ч (НФТ-9)
    },
}


@celery_app.task(name="kb.run_pipeline", bind=True, max_retries=3)
def run_pipeline_task(self, version_id: str) -> None:  # noqa: ANN001
    """Пайплайн версии: av → extract → chunk → embed → preview (ЧНК-1)."""

    from app.workers.pipeline import run_pipeline_for_version

    run_pipeline_for_version(uuid.UUID(version_id))


@celery_app.task(name="kb.reconcile_jobs")
def reconcile_jobs_task() -> None:
    """Реконсиляция: jobs running без прогресса дольше N минут → перевыставление (§13.1)."""

    from datetime import UTC, datetime, timedelta

    from sqlalchemy import text as _sql

    from app.workers.pipeline import _session_factory

    session = _session_factory()()
    try:
        stale = session.execute(
            _sql(
                """
                SELECT version_id::text, step::text FROM jobs
                WHERE status = 'running' AND updated_at < :cutoff
                """
            ),
            {"cutoff": datetime.now(UTC) - timedelta(minutes=10)},
        ).fetchall()
        for version_id, step in stale:
            session.execute(
                _sql("UPDATE jobs SET status='pending', updated_at=now() WHERE version_id=:v AND step=:s"),
                {"v": version_id, "s": step},
            )
            run_pipeline_task.delay(version_id)  # перевыставление всего пайплайна с неп.done-шагов
        session.commit()
    finally:
        session.close()


@celery_app.task(name="kb.cleanup_idempotency")
def cleanup_idempotency_task() -> None:
    """Очистка просроченных Idempotency-Key — TTL обеспечивает Valkey; задача — no-op контроль."""

    return None
