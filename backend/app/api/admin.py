"""Административные обработчики (api-spec §7; системный админ, ПРВ-5)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal, get_db
from app.common.authz import is_admin
from app.common.errors import PermissionDenied
from app.common.security.jwt import Principal

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(principal: Principal) -> None:
    if not is_admin(principal):
        raise PermissionDenied("Только системный администратор")


@router.get("/chunkers")
def list_chunkers(
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Реестр чанкеров: builtin + плагины (ЧНК-8)."""

    _require_admin(principal)
    from app.domain.indexing.chunkers import CHUNKERS

    rows = session.execute(
        text("SELECT name, builtin, is_loaded, error FROM chunker_registry ORDER BY name")
    ).all()
    registered = {r[0]: r for r in rows}
    # синхронизация: builtin-чанкеры всегда видны
    out = []
    for name in sorted(set(registered) | set(CHUNKERS)):
        if name in registered:
            out.append({"name": name, "builtin": registered[name][1], "is_loaded": registered[name][2], "error": registered[name][3]})
        else:
            out.append({"name": name, "builtin": True, "is_loaded": True, "error": None})
    return out


@router.post("/chunkers/reload")
def reload_chunkers(
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Перечитать каталог плагинов без пересборки (ЧНК-3)."""

    _require_admin(principal)
    from app.domain.indexing.plugins import reload_plugins

    loaded = reload_plugins(session)
    return {"loaded": loaded}


@router.get("/settings")
def get_settings_all(
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Настройки системы (не секреты, НФТ-5)."""

    _require_admin(principal)
    rows = session.execute(text("SELECT key, value, updated_at FROM settings ORDER BY key")).all()
    return [{"key": r[0], "value": r[1], "updated_at": r[2]} for r in rows]


@router.put("/settings/{key}")
def put_setting(
    key: str,
    value: dict,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Обновление настройки (изменения через админку, не env — НФТ-5)."""

    _require_admin(principal)
    from app.models.pipeline import Setting

    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    session.commit()
    return {"key": key, "value": value}


@router.post("/reindex")
def reindex(
    payload: dict,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Переиндексация: {scope: 'group'|'all', group_id?} (ЧНК-9)."""

    _require_admin(principal)
    from app.workers.celery_app import run_pipeline_task

    scope = payload.get("scope", "all")
    if scope == "group":
        rows = session.execute(
            text(
                """
                SELECT v.id::text FROM material_versions v
                JOIN materials m ON m.id = v.material_id
                JOIN groups g ON g.id = m.group_id
                WHERE m.current_version_id = v.id
                  AND (g.path @> (SELECT path FROM groups WHERE id = :gid)
                       OR g.id = :gid)
                """
            ),
            {"gid": str(payload.get("group_id"))},
        ).fetchall()
    else:
        rows = session.execute(
            text("SELECT id::text FROM material_versions WHERE id IN (SELECT current_version_id FROM materials)")
        ).fetchall()
    for (vid,) in rows:
        run_pipeline_task.delay(vid)
    return {"queued": len(rows)}


@router.get("/jobs")
def list_jobs(
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Задачи пайплайна: статусы, ошибки (api-spec §7)."""

    _require_admin(principal)
    rows = session.execute(
        text(
            """
            SELECT j.id::text, j.version_id::text, j.step::text, j.status::text, j.attempts, j.error, j.updated_at
            FROM jobs j ORDER BY j.updated_at DESC LIMIT 200
            """
        )
    ).all()
    return [
        {"id": r[0], "version_id": r[1], "step": r[2], "status": r[3], "attempts": r[4], "error": r[5], "updated_at": r[6]}
        for r in rows
    ]


@router.get("/audit")
def audit_log(
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Журнал аудита (только чтение, НФТ-1; полное покрытие — Этап 3)."""

    _require_admin(principal)
    rows = session.execute(
        text(
            "SELECT id, at, actor_id::text, action, object_type, object_id::text, details "
            "FROM audit_log ORDER BY at DESC LIMIT 200"
        )
    ).all()
    return [
        {"id": r[0], "at": r[1], "actor_id": r[2], "action": r[3], "object_type": r[4], "object_id": r[5], "details": r[6]}
        for r in rows
    ]
