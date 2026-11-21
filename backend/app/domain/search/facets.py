"""Фасеты поиска (ПСК-3): агрегированные счётчики по статусу, группе, атрибутам.

Считаются по видимой части выдачи (до top_k-обрезки — по полному множеству совпадений
в пределах прав; ПРВ-9 применяется до агрегации).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common.security.jwt import Principal


def build_facets(session: Session, principal: Principal, hits: list) -> dict[str, list[dict[str, Any]]]:
    """Фасеты по результатам поиска: статус, группа, атрибуты (ПСК-3).

    hits — результаты поиска (уже отфильтрованы по правам, ПРВ-9).
    """

    material_ids = [str(h.material_id) for h in hits if h.type == "material" and h.material_id]
    if not material_ids:
        return {"status": [], "group": [], "attributes": []}

    rows = session.execute(
        text(
            """
            SELECT m.status::text, m.group_id::text, g.name, v.attributes
            FROM materials m
            JOIN groups g ON g.id = m.group_id
            JOIN material_versions v ON v.id = m.current_version_id
            WHERE m.id = ANY(CAST(:mids AS uuid[]))
            """
        ),
        {"mids": material_ids},
    ).fetchall()

    status_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}
    attr_counts: dict[str, dict[str, int]] = {}
    for status, gid, gname, attributes in rows:
        status_counts[status] = status_counts.get(status, 0) + 1
        gkey = f"{gid}|{gname}"
        group_counts[gkey] = group_counts.get(gkey, 0) + 1
        if isinstance(attributes, dict):
            for k, v in attributes.items():
                if isinstance(v, (str, int, float, bool)):
                    attr_counts.setdefault(k, {})
                    skey = str(v)
                    attr_counts[k][skey] = attr_counts[k].get(skey, 0) + 1

    return {
        "status": [{"value": k, "count": n} for k, n in sorted(status_counts.items())],
        "group": [
            {"value": k.split("|")[0], "label": k.split("|")[1], "count": n}
            for k, n in sorted(group_counts.items(), key=lambda kv: -kv[1])
        ],
        "attributes": [
            {"key": k, "values": [{"value": v, "count": n} for v, n in sorted(vals.items(), key=lambda kv: -kv[1])]}
            for k, vals in attr_counts.items()
        ],
    }
