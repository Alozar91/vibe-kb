# Deployment (стенды, окружение, наблюдаемость)

- **Статус:** рабочий документ (v0.2, 2026-11-20)
- **Основа:** §3, §13, §15 концепции; `code-standards.md` (конфиг через pydantic-settings, секреты в env).
- **Стенды и TLS (уточнено 2026-11-20):** доменное имя `merch-vibe.ru` **есть**, TLS-сертификата **пока нет**. `dev` — docker-compose локально, `http://merch-vibe.ru` или localhost; `приёмочный` — тот же сервер, `https://merch-vibe.ru/know` — **после выпуска сертификата** (до этого — HTTP); `prod` — после приёмки.
- **Решения от 2026-11-20:** публичный адрес `https://merch-vibe.ru/know` (base-path `/know`); эмбеддинги — `BAAI/bge-m3`, dense **1024**, до 8192 токенов, мультиязычная (MIT); Python **3.12**, Node **22 LTS**.

## 1.1 Публичные адреса и base-path (решение)

| Адрес | Что за ним | Примечание |
|---|---|---|
| `https://merch-vibe.ru/know` | React SPA | `vite base = '/know/'`, роутер `basename='/know'` |
| `https://merch-vibe.ru/know/api/v1/…` | FastAPI | внутренний путь `/api/v1`; nginx проксирует `/know/api/` → `api:8000` |
| `https://merch-vibe.ru/know/mcp` | MCP | nginx → `mcp:8100` |
| `https://merch-vibe.ru/auth` (предложение) | Keycloak | `KC_HTTP_RELATIVE_PATH=/auth` — один сертификат на `merch-vibe.ru`, без поддомена; issuer: `…/auth/realms/corp-kb` |

- Суффикс `/know` не влияет на SPN Kerberos: он строится по хосту — `HTTP/merch-vibe.ru` (актуально, когда появится корпоративная сеть, §7).


---

## 1. Состав сервисов (docker-compose)

| Сервис | Образ | Порты | Том / примечание |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg17` | 5432 (внутр.) | том `pg_data`; две БД: `kb` и `keycloak` |
| `valkey` | `valkey/valkey:9` | 6379 (внутр.) | брокер Celery + кэш прав + rate-limit; persistence AOF |
| `silo` | `pgsty/silo` | 9000/9001 (внутр.) | том `silo_data`; buckets: `kb-files`, `kb-previews` |
| `keycloak` | `quay.io/keycloak/keycloak:26` | 8080 (внутр.) | БД `keycloak` в общем Postgres; realm `corp-kb` — см. `auth-setup.md` |
| `api` | сборка `backend/` | 8000 (внутр.) | FastAPI (uvicorn, sync-воркеры); `/metrics` |
| `worker` | тот же образ `backend/` | — | Celery worker: пайплайн, конвертация, уведомления |
| `beat` | тот же образ `backend/` | — | Celery beat: плановые задачи (§5) |
| `mcp` | тот же образ `backend/` | 8100 (внутр.) | MCP-сервер (Streamable HTTP) |
| `converter` | сборка `tools/converter/` | 8200 (внутр.) | тонкий HTTP-сервис над LibreOffice headless (`soffice --convert-to pdf`) |
| `frontend` | сборка `frontend/` (nginx) | **80/443 наружу** | статика React (base `/know/`) + reverse proxy на `api`/`mcp`; HTTPS — после выпуска сертификата |
| `tei` *(профиль `models`, опционально)* | `ghcr.io/huggingface/text-embeddings-inference` | 8090 (внутр.) | OpenAI-compatible `/v1/embeddings` с `BAAI/bge-m3` (1024); на dev — профиль `models` или внешний эндпоинт |

- Наружу открыт только `frontend` (nginx: `/*` → статика, `/api` → `api`, `/mcp` → `mcp`, `/metrics` — только из внутренней сети).
- `dev`-отличие: без TLS; vite dev-server на хосте для фронта (proxy на `api`).

## 2. Переменные окружения (`.env.example` в git; сам `.env` — нет)

```
# --- БД ---
KB_DB_URL=postgresql+psycopg://kb:***@postgres:5432/kb
# --- Хранилище/кэш ---
KB_S3_ENDPOINT=http://silo:9000
KB_S3_ACCESS_KEY=***            # секрет
KB_S3_SECRET_KEY=***            # секрет
KB_VALKEY_URL=redis://valkey:6379/0
# --- Аутентификация (см. auth-setup.md §5) ---
KB_KEYCLOAK_ISSUER=https://merch-vibe.ru/auth/realms/corp-kb
KB_KEYCLOAK_AUDIENCES=kb-rag,kb-mcp
KC_DB_URL=...                   # БД Keycloak
KC_BOOTSTRAP_ADMIN_USERNAME/PASSWORD=***   # секрет, только первый запуск
KC_VAULT=file
KC_VAULT_FILE_DIR=/opt/keycloak/vault      # ldap_bind_password и др.
KC_HOSTNAME=merch-vibe.ru
KC_HTTP_RELATIVE_PATH=/auth
# --- Модели (OpenAI-compatible) ---
KB_EMBEDDINGS_BASE_URL=http://tei:8090/v1     # или внешний OpenAI-compatible эндпоинт
KB_EMBEDDINGS_API_KEY=***       # секрет (для TEI может быть заглушкой)
KB_EMBEDDINGS_MODEL=bge-m3
KB_EMBEDDINGS_DIMS=1024         # BAAI/bge-m3, dense; до 8192 токенов
KB_LLM_BASE_URL=***
KB_LLM_API_KEY=***              # секрет
KB_LLM_MODEL=***                # выбрать к Этапу 2 (with_answer)
# --- Почта ---
KB_SMTP_HOST=***
KB_SMTP_USER=***                # секрет
KB_SMTP_PASSWORD=***            # секрет
KB_SMTP_FROM=noreply@merch-vibe.ru
# --- Прочее ---
KB_UPLOAD_MAX_SIZE_MB=50        # дубль настройки в БД (значение по умолчанию)
KB_IDEMPOTENCY_TTL_HOURS=24
```

Правила: секреты помечены `***` и существуют только в `.env`/секрет-хранилище; `.env` в `.gitignore`; изменение значений настроек системы — через админку (БД), не через env (НФТ-5).

## 3. Наблюдаемость (логи + метрики)

**Логи** — структурированный JSON в stdout каждого сервиса:

```json
{"ts": "...", "level": "info", "service": "api", "request_id": "uuid",
 "user": "sub", "action": "material.version.upload", "status": 200, "ms": 143}
```

- `request_id` — из `Idempotency-Key` либо сгенерированный; проставляется middleware и тянется во все записи запроса, в задачи Celery (пробрасывается явно) и в audit_log.
- **Не логировать:** содержимое файлов и чанков, персональные данные кроме `sub`, секреты/токены.
- Уровни: `debug` (только dev), `info` (операции), `warning` (fallback чанкера ЧНК-8, ретраи), `error` (падения шагов).

**Метрики** — `GET /metrics` (Prometheus) на `api` и `worker` (НФТ-6):

- `kb_queue_depth{queue}`, `kb_index_lag_versions`, `kb_job_failed_total{step}`,
- `kb_convert_duration_seconds`, `kb_search_duration_seconds{mode}`,
- `kb_http_requests_total{code}`, `kb_embed_tokens_total` (расход модели).

Алерты (минимум): очередь не пустеет > N минут; `kb_index_lag_versions` растёт; доля 5xx > порога.

## 4. Плановые задачи (Celery beat)

| Задача | Период | Основание |
|---|---|---|
| Реконсиляция очереди (перевыставление «зависших» задач) | 5 мин | §13.1 |
| Очистка просроченных Idempotency-Key | 1 ч | НФТ-9 (TTL 24 ч) |
| Сверка целостности S3 ↔ БД | сутки | НФТ-2 |
| Доставка email-уведомлений | из очереди по событию | УВЕД-1 |
| Бэкап (dev: `pg_dump` + `mc mirror`) | сутки | НФТ-2 |

## 5. Чек-лист первого запуска (dev)

1. `cp .env.example .env`, заполнить секреты.
2. `docker compose up -d postgres valkey silo` → дождаться готовности.
3. `alembic upgrade head` (backend-контейнер) — схема из `data-model.md`.
4. `docker compose up -d keycloak` → настроить realm по `auth-setup.md` (LDAP/Kerberos — на приёмочном; на dev — локальные пользователи).
5. Bootstrap: скрипт первичной настройки — системный админ + первая корневая группа + выдача первичных ролей (ПРВ-8).
6. `docker compose up -d api worker beat mcp converter frontend`.
7. Smoke-тест: `/api/v1/health` 200; вход локальным пользователем; загрузка тестового файла (пройти полный пайплайн); поиск находит; скачивание отдаёт оригинал; аудиторская запись создана.

## 6. Приёмочный стенд (отличия от dev)

- TLS на nginx + hostname = SPN из AD-2/AD-3 (`auth-setup.md`).
- LDAP federation + Kerberos включены; GPO браузеров развернуты (AD-6).
- Бэкапы по расписанию с хранением; мониторинг включён; алерты настроены.
- Обновления: миграции до новой версии приложения, `rolling` не требуется (один инстанс), проверка после деплоя по чек-листу §5 (шаг 7 — smoke-тест).

## 7. Решённые и оставшиеся вопросы

**Решено (2026-11-20):**

| Вопрос | Решение |
|---|---|
| Публичный адрес | `https://merch-vibe.ru/know` (base-path `/know`); Keycloak — `https://merch-vibe.ru/auth` (§1.1, подтверждено) |
| Модель эмбеддингов | `BAAI/bge-m3` — dense 1024, до 8192 токенов, 100+ языков, MIT; хостинг — TEI или любой OpenAI-compatible |
| Версии | Python 3.12, Node 22 LTS |

**Статус TLS (уточнено 2026-11-20):** доменное имя `merch-vibe.ru` — есть; TLS-сертификата — пока нет. Приёмочный стенд стартует по HTTP; HTTPS включается выпуском сертификата (Let's Encrypt или коммерческий — на выбор владельца сервера); redirect HTTP→HTTPS и HSTS включаются в момент перехода на TLS.

**Осталось:**

| Вопрос | Влияет на |
|---|---|
| LLM для `with_answer` | настройки `KB_LLM_*` (Этап 2) |
| Появление корпоративной сети/AD | LDAP federation, Kerberos/SPN (`HTTP/merch-vibe.ru`), задачи AD-1…7 из auth-setup |
| TLS-сертификат `merch-vibe.ru` | переключение приёмочного стенда на HTTPS (НФТ-3); до выпуска сертификата стенд — HTTP, отступление от НФТ-3 осознанное и временное |

## 8. Что НЕ входит сюда

Runbook эксплуатации (реагирование на инциденты) — после опытной эксплуатации; модель угроз отдельным документом не ведём (§15 достаточно для MVP); Kubernetes-манифесты — после решения о прод-стенде.
