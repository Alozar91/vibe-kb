# AGENTS.md

## Проект

Корпоративная база знаний (vibe-kb): централизованное хранение, учёт, поиск (полнотекстовый, атрибутный, векторный, гибридный) и RAG (API + MCP) по корпоративным материалам. Аутентификация — Keycloak (пароль, LDAP, Kerberos/SPNEGO).

## Стадия и правила

- Концепция **принята** (v1.0, `docs/concept.md`); разработка идёт по этапам §18, начиная с Этапа 0.
- Вся документация живёт в `docs/` и пишется **на русском языке**; индекс — `docs/README.md`.
- Источники истины по областям: `docs/concept.md` — архитектура и решения; `docs/requirements.md` — функциональные требования (REQ-ID: АУТ/ГРП/МАТ/ВЕРС/СТАТ/ПРВ/ЧНК/ПСК/РАГ/ПРС/УВЕД/НФТ) с критериями приёмки; `docs/data-model.md` — схема БД и индексы; `docs/api-spec.md` — контракт API; `docs/auth-setup.md` — Keycloak/AD.
- Новые функциональные требования фиксируются в `docs/requirements.md` (новый REQ-ID) и в матрице соответствия §17 концепции. Изменения схемы БД — только через `docs/data-model.md` + миграцию Alembic; изменения API — через `docs/api-spec.md` и OpenAPI-файл кода.
- Идемпотентность обязательна (НФТ-9, §13.2 концепции): `Idempotency-Key` клиента на изменяющих операциях API (для загрузки файлов — строго), детерминированные ключи шагов пайплайна (`version_id` + шаг), append-only журнал статусов.
- Правила построения кода — `docs/code-standards.md` (приняты): вертикальные срезы, слои `api → services → repositories`, прагматичный UoW, sync-first, TanStack Query и feature-sliced на фронте. Изменения стандарта — через правку документа/ADR.

## Стек (зафиксирован в концепции)

- Backend: Python + FastAPI (SQLAlchemy 2 + Alembic, Celery); frontend: React + TypeScript, UI-кит — Ant Design 5.
- PostgreSQL; кэш и очередь задач — **Valkey, не Redis** (Kafka/RabbitMQ — только по триггерам, `docs/concept.md` §13.1); объектное хранилище — **Silo** (`pgsty/silo`, S3-совместимый форк MinIO), не MinIO; вектора — pgvector (старт) с триггерами миграции на Qdrant.
- Модели (эмбеддинги/LLM) — только по OpenAI-совместимому API.

## Git

- Remote `origin` → `https://github.com/Alozar91/vibe-kb.git`, основная ветка `master`.
- Правило владельца: **каждый коммит сразу отправлять в origin**, не копить локальные коммиты.
- Изменения документации вести в ветке `docs`.
- Push работает через `gh auth git-credential` (вход через GitHub CLI под `Alozar91`); локальный `user.name`/`user.email` заданы в конфиге репозитория.
