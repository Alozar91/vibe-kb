# Контракт API

- **Статус:** рабочий документ (v0.1, 2026-11-20)
- **Основа:** концепция §8 (права), §10 (поиск), §11 (RAG/MCP), §13.2 (идемпотентность); ТЗ `requirements.md`.
- Уровень детализации: контракт (методы, пути, тела, коды ответов, права). Полный OpenAPI-файл генерируется FastAPI и дополняется в репозитории кода; этот документ — источник соглашений.

---

## 1. Общие положения

- Базовый путь: `https://<host>/api/v1`.
- Аутентификация: `Authorization: Bearer <JWT>` (Keycloak; проверка `iss`/`aud`/подписи по JWKS — АУТ-5).
- **`Idempotency-Key: <uuid>`** (стандартный HTTP-заголовок):
  - **обязателен** для `POST /materials` (загрузка файла) — АУТ/НФТ-9;
  - фронтенд передаёт на **все** изменяющие операции; интеграции — рекомендован;
  - повтор с тем же ключом возвращает сохранённый результат (кэш в Valkey, TTL 24 ч) без повторного выполнения.
- Формат ошибок: `application/problem+json` (RFC 9457): `{type, title, status, detail, instance}` + опциональные расширения (`violations` для валидации).
- Пагинация списков: `?limit=50&offset=0` (по умолчанию 50, максимум 200), ответ содержит `total`.
- Все тела запросов/ответов — `application/json`, кроме upload/download (multipart / binary).

### Коды ошибок

| Код | Когда |
|---|---|
| 400 | некорректное тело/параметры |
| 401 | нет/просрочен/невалидный токен |
| 403 | нет прав (ПРВ) или операция запрещена ролью |
| 404 | объект не существует или не виден (навигационная видимость, ПРВ-2) |
| 409 | конфликт: недопустимый переход статуса (СТАТ-2), дубликаты имён (ГРП-2/МАТ-4), optimistic locking (ВЕРС), дубликат связи (ВЕРС-4), цикл в дереве (ГРП-1) |
| 413 | файл больше лимита (50 МБ, НФТ-5) |
| 422 | валидация тела (например, пустой `change_comment`), файл без изменений «ничего не изменилось» (ВЕРС-2) |
| 423 | файл ещё не прошёл антивирус-скан (НФТ-4) |
| 429 | rate-limit |

## 2. Группы

| Метод/путь | Описание | Права |
|---|---|---|
| `GET /groups/{id}/children` | дочерние группы с учётом nav-only видимости (ПРВ-2) | любой аутентифицированный (отфильтровано) |
| `GET /groups/{id}/materials` | материалы группы (только при can_read) | Читатель+ |
| `POST /groups/{id}/children` | создание подгруппы `{name, description}` | Владелец родителя (ГРП-4) |
| `PATCH /groups/{id}` | переименование/описание | Владелец группы (ГРП-4) |
| `POST /groups/{id}/move` | перемещение `{new_parent_id}` — Владелец в обеих группах (ГРП-4) | Владелец |
| `DELETE /groups/{id}` | soft-delete пустой группы | Владелец группы (ГРП-3/4) |
| `POST /groups/{id}/restore` | восстановление удалённой группы | Системный администратор (ГРП-4) |
| `GET /groups/{id}/chunker` / `PUT /groups/{id}/chunker` | настройка чанкера `{name, params}` / сброс | **Системный администратор** (ГРП-5) |

## 3. Роли

| Метод/путь | Описание | Права |
|---|---|---|
| `GET /groups/{id}/roles` | список назначенных ролей (с учётом эффективных по иерархии) | Владелец+, Админ |
| `PUT /groups/{id}/roles/{user_id}` | назначение роли `{role}` | Владелец группы или вложенной (ПРВ-7); админ |
| `DELETE /groups/{id}/roles/{user_id}` | отзыв роли | Владелец+, Админ |

- Повтор `PUT` с тем же `Idempotency-Key` — идемпотентен; смена роли инвалидирует кэш прав (ПРВ-9) и порождает событие уведомления (УВЕД-3).

## 4. Материалы

| Метод/путь | Описание | Права |
|---|---|---|
| `POST /groups/{id}/materials` | создание: multipart (`file` + JSON-поля: name, description, attributes, external_links, change_comment); заголовок `Idempotency-Key` **обязателен** | Редактор+ |
| `GET /materials/{id}` | карточка: статусы, версии (список), атрибуты, ссылки, родитель | Читатель+ |
| `PATCH /materials/{id}/content` | новая версия: multipart (`file?` + `description?`, `external_links?`, `attributes?`, `change_comment` обязателен); `If-Match: <current_version_id>` — optimistic locking | Редактор+ |
| `DELETE /materials/{id}` | soft-delete (только из Черновика) | Редактор+ (СТАТ-4) |
| `POST /materials/{id}/copy` | копирование в `{target_group_id}` | Чтение в источнике + Редактор+ в целевой |
| `POST /materials/{id}/move` | перемещение `{target_group_id}` | Редактор+ в обеих группах (МАТ-5) |
| `GET /materials/{id}/versions` | список версий с diff-метаданными | Читатель+ |
| `GET /versions/{vid}/file` | скачивание оригинала (binary stream; через API, ПРС-1) | Читатель+ |
| `GET /versions/{vid}/preview` | PDF-превью / рендер-формат; `423` до скана, `202`-подобная заглушка пока не готово | Читатель+ |
| `POST /materials/{id}/transitions` | смена статуса `{to}` — только допустимые переходы (СТАТ-2); `Idempotency-Key` рекомендован | по таблице §6 |
| `POST /materials/{id}/links` | привязка родителя `{parent_id}` — фиксирует актуальную версию родителя | Редактор+ |
| `PATCH /materials/{id}/links` | перепривязка `{parent_version_id?}` / `DELETE /materials/{id}/links` — отвязка | Редактор+ (ВЕРС-4) |

Ответы со статусами файлов: `av_status`, `text_extracted`, `preview_ready` — в карточке версии; обработка индексации асинхронная (ЧНК-1), ошибки шагов видны в `GET /materials/{id}/versions` и в админке задач.

## 5. Поиск

```
POST /api/v1/search
{
  "query": "текст запроса",          // обязателен для fulltext/vector/hybrid
  "mode": "fulltext" | "vector" | "hybrid" | "attributes",
  "group_ids": ["uuid", ...],        // опционально; фильтруются по правам, вложенные включаются
  "filters": {                       // для mode=attributes и как пост-фильтр
    "attributes": {"ключ": значение | {"in": [...], "gte": ..., "lte": ..., "prefix": ...}},
    "status": ["confirmed", "archived"], "author_id": "uuid", "date_from": "...", "date_to": "..."
  },
  "top_k": 20
}
```

Ответ: `{results: [{type: "material"|"group", material?: {...карточка...}, group?: {...}, snippet, chunk?, version?, score}], facets: {attribute_key: [{value, count}], status: [...], group: [...]}, total}`.

- Гибридный режим — RRF-объединение FTS и векторного (ПСК-1); parent-child — подстановка родительского чанка в результат (ПСК-1).
- Права применяются до выдачи (ПРВ-9); материалы без извлечённого текста — только в режиме метаданных (ПСК-4).

## 6. RAG API

```
POST /api/v1/rag/query
{
  "question": "...",
  "group_ids": ["uuid", ...],   // опционально; фильтруются по правам
  "top_k": 8,
  "with_answer": true,          // false — чистый retrieval
  "stream": false               // true — SSE
}
```

- `with_answer=true`: ответ LLM (OpenAI-compatible, §13) с цитатами `[n]`.
- Ответ: `{answer?, citations: [{n, material_id, version_no, chunk_index, score, link}], retrieved: [...]}`.
- `text/event-stream` при `stream=true`: события `citations`, `token`, `done`.
- Аутентификация: Bearer JWT пользователя или техучётки (§11.3); права — права владельца токена (РАГ-2).

## 7. Административные эндпоинты (Системный администратор)

| Метод/путь | Описание |
|---|---|
| `GET /admin/chunkers` | реестр: builtin+плагины, `code_hash`, `params_schema`, ошибки загрузки (ЧНК-8) |
| `POST /admin/chunkers/reload` | перечитать каталог плагинов, обновить реестр (ЧНК-3) |
| `GET/PUT /admin/settings` | настройки системы (лимиты, модели, дефолтный чанкер, события уведомлений) — не секреты (НФТ-5) |
| `POST /admin/reindex` | запуск переиндексации: `{scope: "group"|"all", dry_run?}` — идемпотентно, прогресс в jobs (ЧНК-9) |
| `GET /admin/jobs` | задачи пайплайна: статусы, ошибки, ретраи |
| `POST /admin/files/{file_id}/rescan` | повторный антивирус/переизвлечение текста (ЧНК-7) |
| `GET /admin/audit` | журнал аудита (только чтение, НФТ-1) |
| `POST /groups/{id}/restore` | восстановление группы (ГРП-4) |

## 8. MCP-сервер (Streamable HTTP, `/mcp`)

| Tool | Вход | Выход |
|---|---|---|
| `search` | query, mode, group_ids?, filters?, limit | те же результаты, что `/search` (без фасетов) |
| `list_tree` | root?, depth | видимые группы с признаком nav-only |
| `get_material` | material_id | карточка: статусы, версии, атрибуты, ссылки |
| `read_chunks` | version_id, диапазон индексов? | тексты чанков с метаданными |
| `read_file` | version_id | содержимое файла (после AV-гейта) |
| `rag_answer` | question, group_ids?, top_k? | ответ с цитатами (обёртка RAG) |

- Аутентификация: OAuth/OIDC через Keycloak, bearer JWT (§11.3). Все инструменты — под правами владельца токена (РАГ-2).
- Ошибки MCP — стандартные коды инструментов (`invalid_params`, `permission_denied`, `not_found`).

## 9. Событие → API (для UI)

- Смена статуса: `POST /materials/{id}/transitions` — тело `{to: "on_review"}`; ответ — новое состояние + запись журнала.
- Optimistic locking правок: `If-Match: <current_version_id>`; при расхождении — `409` с актуальной версией в теле (ВЕРС/§7).
- Фасеты и поиск — один и тот же запрос `POST /search` (счётчики в поле `facets`).
