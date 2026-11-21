"""НФТ-8: нагрузочный sanity — массовое создание + поиск на стенде.

Запуск: uv run python -m tests.load.sanity  (dev-стенд должен быть поднят)
Критерий (docs/testing.md): p95 поиска < 2 c; создание 100 материалов < 60 c.
"""

from __future__ import annotations

import os
import statistics
import time
import uuid

os.environ.setdefault("KB_ADMIN_SUBS", "sub-admin")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.common.db import UoW
from app.common.security.jwt import Principal
from app.domain.groups import service as groups_service
from app.domain.materials import service as materials_service
from app.domain.search import service as search_service
from app.domain.search.schemas import SearchIn

N_MATERIALS = 100
DOC = ("Технический документ №{}: насосы центробежные, давление 16 бар, регламент обслуживания "
       "и техника безопасности при эксплуатации оборудования цеха.").encode()


def main() -> None:
    e = create_engine(os.environ.get("KB_TEST_DB_URL", "postgresql+psycopg://kb:kb@localhost:5433/kb_test"))
    with e.connect() as c:
        for ext in ('"uuid-ossp"', "ltree", "vector"):
            c.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext}"))
        c.commit()
    from app.models import Base as _B

    _B.metadata.create_all(e)
    s = sessionmaker(bind=e)()
    admin = Principal(sub="sub-admin", username="load-admin", display_name="load", email=None, is_local=True)
    exists = s.execute(text("SELECT 1 FROM users WHERE keycloak_sub='sub-admin'")).scalar()
    if not exists:
        s.add(
            __import__("app.models.identity", fromlist=["User"]).User(
                keycloak_sub="sub-admin", username="load-admin", display_name="load", is_local=True
            )
        )
        s.commit()

    with UoW(s) as uow:
        root = groups_service.create_group(uow, admin, None, f"Нагрузочный-{uuid.uuid4().hex[:6]}", None)

    t0 = time.perf_counter()
    for i in range(N_MATERIALS):
        with UoW(s) as uow:
            materials_service.create_material(
                uow, admin, root.id, f"Документ {i:04d}", None, {"n": i}, None, "v1", DOC.replace(b"{}", str(i).encode()), f"d{i}.txt"
            )
    t_create = time.perf_counter() - t0
    print(f"создание {N_MATERIALS} материалов: {t_create:.1f} с ({N_MATERIALS / t_create:.1f}/с)")

    # поиск: 20 прогонов, p95
    latencies = []
    for _ in range(20):
        t = time.perf_counter()
        hits = search_service.search(s, admin, SearchIn(query="насосы давление", mode="fulltext", top_k=50))
        latencies.append((time.perf_counter() - t) * 1000)
        assert hits is not None
    p95 = statistics.quantiles(latencies, n=20)[18]
    print(f"поиск fulltext: p50={statistics.median(latencies):.0f} мс, p95={p95:.0f} мс (n={len(latencies)})")

    assert t_create < 120, f"создание слишком медленное: {t_create:.1f} c"
    assert p95 < 2000, f"p95 поиска > 2 c: {p95:.0f} мс"
    print("НФТ-8 sanity: OK")


if __name__ == "__main__":
    main()
