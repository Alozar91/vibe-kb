"""Поиск (ПСК-1..5): FTS (russian/english), атрибуты (jsonb+GIN), вектор (pgvector KNN), гибрид RRF.

Права применяются до выдачи (ПСК-4, ПРВ-9): фильтр по visible_group_ids.
Материалы без извлечённого текста — только в метаданных (ПСК-4); ищутся только актуальные версии (ВЕРС-3).
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common.security.jwt import Principal
from app.domain.search.schemas import SearchHit, SearchIn

RRF_K = 60  # константа RRF (ПСК-1)


def _allowed_groups(session: Session, principal: Principal, requested: list[uuid.UUID] | None) -> list[str]:
    """Пересечение запрошенных групп с видимыми (ПРВ-9); вложенные включаются по path."""

    visible = set(visible_ids(session, principal))
    if requested is None:
        return list(visible)
    return [str(g) for g in requested if str(g) in visible]


def visible_ids(session: Session, principal: Principal) -> list[str]:
    from app.common.authz import visible_group_ids

    return visible_group_ids(session, principal)


def _group_uuids_with_subtree(session: Session, principal: Principal, group_ids: list[str]) -> list[str]:
    """Разрешить поддеревья ТОЛЬКО в пределах видимых групп (ПРВ-9: права до выдачи).

    Расширение вниз ограничено поддеревьями групп с ролью (ПРВ-1); предки с nav_only
    (ПРВ-2) содержимое своих поддеревьев не открывают. Группы с ролью — content-доступ.
    """

    if not group_ids:
        return []

    from app.common.authz import is_admin

    if is_admin(principal):
        # Админ видит всё: расширение без фильтра по ролям (ПРВ-5)
        rows = session.execute(
            text(
                """
                SELECT DISTINCT g2.id::text FROM groups g1
                JOIN groups g2 ON g1.path @> g2.path
                WHERE g1.id = ANY(CAST(:gids AS uuid[])) AND NOT g2.is_deleted
                """
            ),
            {"gids": group_ids},
        ).fetchall()
        return [r[0] for r in rows]

    # Группы, где у пользователя есть роль (полный доступ к поддереву, ПРВ-1)
    granted_rows = session.execute(
        text(
            """
            SELECT DISTINCT g.id::text, g.path::text
            FROM group_roles gr
            JOIN groups g ON g.id = gr.group_id
            WHERE gr.user_id = (SELECT id FROM users WHERE keycloak_sub = :sub)
            """
        ),
        {"sub": principal.sub},
    ).fetchall()
    granted_ids = {r[0] for r in granted_rows}

    # Все потомки запрошенных групп (техническое расширение поддеревьев)
    rows = session.execute(
        text(
            """
            SELECT DISTINCT g2.id::text FROM groups g1
            JOIN groups g2 ON g1.path @> g2.path
            WHERE g1.id = ANY(CAST(:gids AS uuid[])) AND NOT g2.is_deleted
            """
        ),
        {"gids": group_ids},
    ).fetchall()
    expanded = {r[0] for r in rows}

    # Фильтр: группа доступна, если (а) сама granted, или (б) лежит под granted-предком
    result: list[str] = []
    for gid in expanded:
        if gid in granted_ids:
            result.append(gid)
            continue
        under = session.execute(
            text(
                """
                SELECT 1 FROM groups g
                WHERE g.id = CAST(:gid AS uuid)
                  AND EXISTS (
                      SELECT 1 FROM groups anc
                      WHERE anc.id = ANY(CAST(:gids AS uuid[])) AND anc.path @> g.path
                  )
                LIMIT 1
                """
            ),
            {"gid": gid, "gids": list(granted_ids) or ["00000000-0000-0000-0000-000000000000"]},
        ).scalar()
        if under:
            result.append(gid)
    return result


def _fts_query(session: Session, principal: Principal, payload: SearchIn, allowed: list[str]) -> list[SearchHit]:
    """Полнотекстовый поиск: chunks.tsv_ru/tsv_en OR + name_tsv + description_tsv (ПСК-1, ПСК-5)."""

    q = payload.query or ""
    limit = payload.top_k
    rows = session.execute(
        text(
            """
            WITH allowed AS (SELECT unnest(CAST(:allowed AS uuid[])) AS id),
            -- группы (ПСК-2)
            g_hits AS (
                SELECT 'group' AS type, g.id::text AS gid, NULL::text AS mid, NULL::text AS vid,
                       g.name, NULL::text AS chunk, NULL::int AS chunk_index,
                       ts_rank_cd(g.name_tsv, query) AS rank
                FROM groups g, websearch_to_tsquery('russian', :q) query
                WHERE g.id IN (SELECT id FROM allowed) AND NOT g.is_deleted
                  AND (g.name_tsv @@ query OR g.description_tsv @@ query)
            ),
            m_hits AS (
                SELECT 'material' AS type, NULL::text AS gid, m.id::text AS mid, v.id::text AS vid,
                       m.name, c.text AS chunk, c.chunk_index,
                       GREATEST(
                           ts_rank_cd(c.tsv_ru, q_ru), ts_rank_cd(c.tsv_en, q_en),
                           ts_rank_cd(m.name_tsv, q_ru)
                       ) AS rank
                FROM materials m
                JOIN groups g ON g.id = m.group_id
                JOIN material_versions v ON v.id = m.current_version_id
                LEFT JOIN chunks c ON c.version_id = v.id
                , websearch_to_tsquery('russian', :q) q_ru, websearch_to_tsquery('english', :q) q_en
                WHERE m.group_id IN (SELECT id FROM allowed) AND NOT m.is_deleted
                  AND (c.tsv_ru @@ q_ru OR c.tsv_en @@ q_en OR m.name_tsv @@ q_ru OR v.description_tsv @@ q_ru
                       OR c.tsv_ru @@ q_en OR c.tsv_en @@ q_en)
            )
            SELECT * FROM g_hits
            UNION ALL
            SELECT * FROM m_hits
            ORDER BY rank DESC LIMIT :limit
            """
        ),
        {"q": q, "allowed": allowed or ["00000000-0000-0000-0000-000000000000"], "limit": limit},
    ).mappings().all()
    return [_row_to_hit(r) for r in rows]


def _attributes_query(session: Session, principal: Principal, payload: SearchIn, allowed: list[str]) -> list[SearchHit]:
    """Поиск по атрибутам и метаданным (jsonb @> + GIN, ПСК-1); без текста — только метаданные (ПСК-4)."""

    conditions = []
    params: dict = {"allowed": allowed or ["00000000-0000-0000-0000-000000000000"], "limit": payload.top_k}
    if payload.filters and payload.filters.attributes:
        for i, (key, value) in enumerate(payload.filters.attributes.items()):
            p = f"a{i}"
            if isinstance(value, dict):
                for op, operand in value.items():
                    if op == "in":
                        conditions.append(f"v.attributes->>{key!r} = ANY(:{p}_in)")
                        params[f"{p}_in"] = [str(x) for x in operand]
                    elif op == "gte":
                        conditions.append(f"(v.attributes->>{key!r})::numeric >= :{p}_gte")
                        params[f"{p}_gte"] = float(operand)
                    elif op == "lte":
                        conditions.append(f"(v.attributes->>{key!r})::numeric <= :{p}_lte")
                        params[f"{p}_lte"] = float(operand)
                    elif op == "prefix":
                        conditions.append(f"v.attributes->>{key!r} ILIKE :{p}_prefix || '%'")
                        params[f"{p}_prefix"] = str(operand)
            else:
                conditions.append("v.attributes @> :attr_full")
                params["attr_full"] = __import__("json").dumps({key: value})
    where = " AND ".join(conditions) if conditions else "TRUE"
    rows = session.execute(
        text(
            f"""
            SELECT 'material' AS type, NULL::text AS gid, m.id::text AS mid, v.id::text AS vid,
                   m.name, NULL::text AS chunk, NULL::int AS chunk_index, 1.0 AS rank
            FROM materials m
            JOIN material_versions v ON v.id = m.current_version_id
            WHERE m.group_id = ANY(CAST(:allowed AS uuid[])) AND NOT m.is_deleted AND ({where})
            ORDER BY m.updated_at DESC LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    return [_row_to_hit(r) for r in rows]


def _vector_query(session: Session, principal: Principal, payload: SearchIn, allowed: list[str]) -> list[SearchHit]:
    """Векторный KNN по эмбеддингам чанков актуальных версий (ПСК-1, ВЕРС-3).

    Эмбеддинг запроса вычисляется через embeddings-клиент (OpenAI-compatible, РАГ-3).
    """

    from app.domain.indexing.embeddings import embed_query

    if not payload.query:
        return []
    vector = embed_query(payload.query)
    rows = session.execute(
        text(
            """
            SELECT 'material' AS type, NULL::text AS gid, m.id::text AS mid, v.id::text AS vid,
                   m.name, c.text AS chunk, c.chunk_index,
                   1 - ((c.embedding::halfvec) <=> CAST(:vec AS halfvec)) AS rank
            FROM chunks c
            JOIN material_versions v ON v.id = c.version_id
            JOIN materials m ON m.id = c.material_id
            WHERE m.group_id = ANY(CAST(:allowed AS uuid[])) AND NOT m.is_deleted
              AND v.id = m.current_version_id
            ORDER BY c.embedding::halfvec <=> CAST(:vec AS halfvec)
            LIMIT :limit
            """
        ),
        {"vec": vector, "allowed": allowed or ["00000000-0000-0000-0000-000000000000"], "limit": payload.top_k},
    ).mappings().all()
    return [_row_to_hit(r) for r in rows]


def _hybrid_query(session: Session, principal: Principal, payload: SearchIn, allowed: list[str]) -> list[SearchHit]:
    """Гибрид: RRF-объединение FTS и векторного (ПСК-1)."""

    fts = _fts_query(session, principal, payload, allowed)
    vec = _vector_query(session, principal, payload, allowed)
    scores: dict[tuple, float] = {}
    hits: dict[tuple, SearchHit] = {}
    for rank, h in enumerate(fts, start=1):
        k = (h.type, str(h.material_id or h.group_id), h.chunk_index)
        scores[k] = scores.get(k, 0.0) + 1.0 / (RRF_K + rank)
        hits.setdefault(k, h)
    for rank, h in enumerate(vec, start=1):
        k = (h.type, str(h.material_id or h.group_id), h.chunk_index)
        scores[k] = scores.get(k, 0.0) + 1.0 / (RRF_K + rank)
        hits.setdefault(k, h)
    ordered = sorted(scores.items(), key=lambda kv: -kv[1])[: payload.top_k]
    return [hits[k].model_copy(update={"score": s}) for k, s in ordered]


def _row_to_hit(r) -> SearchHit:
    return SearchHit(
        type=r["type"],
        material_id=uuid.UUID(r["mid"]) if r["mid"] else None,
        group_id=uuid.UUID(r["gid"]) if r["gid"] else None,
        name=r["name"] or "",
        snippet=(r["chunk"] or "")[:200] if r["chunk"] else None,
        chunk=r["chunk"],
        version_id=uuid.UUID(r["vid"]) if r["vid"] else None,
        chunk_index=r["chunk_index"],
        score=float(r["rank"] or 0),
    )


def search(session: Session, principal: Principal, payload: SearchIn) -> list[SearchHit]:
    """Единая точка поиска: права до выдачи (ПСК-4, ПРВ-9)."""

    requested = payload.group_ids
    allowed = _group_uuids_with_subtree(session, principal, _allowed_groups(session, principal, requested))
    if payload.mode == "fulltext":
        return _fts_query(session, principal, payload, allowed)
    if payload.mode == "vector":
        return _vector_query(session, principal, payload, allowed)
    if payload.mode == "hybrid":
        return _hybrid_query(session, principal, payload, allowed)
    return _attributes_query(session, principal, payload, allowed)
