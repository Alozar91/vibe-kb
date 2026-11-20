# Модель данных

- **Статус:** рабочий документ (v0.1, 2026-11-20)
- **Основа:** §5, §6, §8, §13.2 концепции; ТЗ `requirements.md`.
- **СУБД:** PostgreSQL 17+ (pgvector для чанков и векторов — решение §14).
- **Соглашения:** первичные ключи — `uuid` (gen_random_uuid()); время — `timestamptz`; названия таблиц/колонок — `snake_case`; логическое удаление — `is_deleted boolean not null default false` + `deleted_at timestamptz`, `deleted_by uuid` (там, где применимо); у каждой сущности — `created_at`, `created_by`, `updated_at`, `updated_by` (далее «аудиторские поля»); миграции — Alembic.

---

## 1. users — пользователи системы

| Поле | Тип | Описание |
|---|---|---|
| id | uuid PK | |
| keycloak_sub | text unique not null | `sub` из JWT; маппинг на пользователя Keycloak |
| username | text unique not null | из Keycloak |
| display_name | text not null | |
| email | text | для уведомлений |
| is_local | boolean not null | пользователь без привязки к AD (АУТ-3) |
| is_blocked | boolean not null default false | блокировка (уход из AD / решение админа, АУТ-4) |

- Синхронизация: при каждом входе обновляются `username/display_name/email`. Строки **не удаляются** (АУТ-4): авторство и роли сохраняются.
- На пользователя не ссылаются FK-каскады ни из одной таблицы.

## 2. groups — группы

| Поле | Тип | Описание |
|---|---|---|
| id | uuid PK | |
| parent_id | uuid FK→groups, nullable | null — корневая |
| name | text not null | |
| description | text | |
| is_deleted / deleted_at / deleted_by | | soft-delete (ГРП-3) |
| + аудиторские поля | | |

Индексы и ограничения:

```sql
-- ГРП-2: уникальность имени среди не удалённых в рамках родителя.
-- NULL'ы различимы в обычном уникальном индексе, поэтому coalesce/UNIQUE NULLS NOT DISTINCT:
CREATE UNIQUE INDEX uq_groups_name_alive
  ON groups (coalesce(parent_id, uuid_nil()), lower(trim(name)))
  WHERE NOT is_deleted;

-- Быстрое раскрытие поддерева (материализация пути):
ALTER TABLE groups ADD COLUMN path ltree NOT NULL;      -- 'root.b.c.d'
CREATE INDEX ix_groups_path ON groups USING gist (path);
-- path поддерживается транзакционно при создании/перемещении/удалении;
-- перемещение поддерева — одна транзакция с пересчётом path всех потомков.
```

- `path` — материализованный путь (ltree) для эффективной проверки «предок/потомок», навигации и выборок прав; главный источник истины — `parent_id`, `path` — поддерживаемый индекс.
- Запрет удаления: проверка «в иерархии нет не удалённых материалов» (ГРП-3) — сервисным кодом + контрольный триггер.
- Восстановление после soft-delete — только системным администратором (решение по итогам ревью).

## 3. group_roles — роли в группах

| Поле | Тип |
|---|---|
| id | uuid PK |
| user_id | uuid FK→users |
| group_id | uuid FK→groups |
| role | enum('reader','editor','reviewer','owner') |

- `unique (user_id, group_id)` — одна роль на пару (роли не суммируются на одном уровне; объединение работает по иерархии, ПРВ-6).
- Изменение ролей → инвалидация кэша прав в Valkey (ПРВ-9).
- Событие «выданы/изменены права» → уведомления (УВЕД-2).

## 4. materials — материалы

| Поле | Тип | Описание |
|---|---|---|
| id | uuid PK | |
| group_id | uuid FK→groups not null | |
| name | text not null | не версионное (идентичность) |
| status | enum('draft','on_review','confirmed','archived','deleted') not null | актуальный статус, см. §6 |
| author_id | uuid FK→users not null | обязательный атрибут (треб. 24), не источник прав |
| current_version_id | uuid FK→material_versions | |
| is_deleted / deleted_at / deleted_by | | синхронно со статусом 'deleted' (СТАТ-4) |
| + аудиторские поля | | |

```sql
CREATE UNIQUE INDEX uq_materials_name_alive
  ON materials (group_id, lower(trim(name)))
  WHERE NOT is_deleted;
```

## 5. material_versions — версии (снимки)

| Поле | Тип | Описание |
|---|---|---|
| id | uuid PK | |
| material_id | uuid FK→materials not null | |
| version_no | integer not null | монотонный в рамках материала |
| file_id | uuid FK→files not null | файл обязателен (МАТ-2); дедупликация по sha256 |
| description | text | в снимке версии (ВЕРС-1) |
| external_links | jsonb | `[{url, label}]`, опционально (МАТ-3) |
| attributes | jsonb | снимок значений атрибутов, GIN-индекс (ПСК-1) |
| change_comment | text not null | обязателен (ВЕРС-1) |
| created_by / created_at | | автор версии |
| reviewers | jsonb | список user_id — Проверяющие группы на момент отправки на проверку (СТАТ-5); null для черновика |
| confirmed_by | uuid FK→users, nullable | кто подтвердил |
| confirmed_at | timestamptz | |
| chunker_name / chunker_version | text, nullable | resolved-чанкер на момент индексации (ЧНК-4) |
| file_sha256 | text not null | снимок хэша файла |

- `unique (material_id, version_no)`.
- `chunker_*` — снимок конфигурации индексации; изменение resolved-чанкера запускает переиндексацию (ЧНК-9).
- При «файл не менялся» — `file_id` указывает на прежний `files.id` (дедупликация хранилища, ВЕРС-2).

### 8.1 FTS-поля названий и описаний (ПСК-1, ПСК-2)

| Таблица.колонка | Обновление | Назначение |
|---|---|---|
| `materials.name_tsv tsvector` | сервисно при переименовании | поиск по названиям материалов |
| `material_versions.description_tsv tsvector` | при создании версии | поиск по описаниям (актуальной версии) |
| `groups.name_tsv / description_tsv tsvector` | при переименовании/правке | поиск по группам (ПСК-2) |

- Все — GIN-индексы; полнотекстовый режим (ПСК-1) ищет по объединению: `chunks.tsv_ru/tsv_en` + `name_tsv` + `description_tsv`.

## 6. files — файлы (объекты хранилища)

| Поле | Тип | Описание |
|---|---|---|
| id | uuid PK | |
| storage_key | text not null | ключ объекта в Silo (S3) |
| original_filename | text not null | как назвал пользователь (отображение) |
| mime | text not null | **детектированный** тип по содержимому (ЧНК-7) |
| size | bigint not null | ≤ лимита из settings (НФТ-5) |
| sha256 | text not null | для дедупликации и версий |
| preview_key | text, nullable | ключ PDF-превью в Silo; пишется атомарно после генерации |
| text_extracted | enum('success','failed','unsupported') not null | исход извлечения текста (ЧНК-7) |
| av_status | enum('pending','clean','infected','skipped_stub') not null | гейт доступа (НФТ-4) |

- `unique (sha256, size)` — дедупликация объектов хранилища: повторная загрузка того же файла переиспользует строку и объект (ВЕРС-2).
- Доступ к объекту — только после `av_status = clean` (или `skipped_stub` в dev-режиме заглушки).

## 7. material_links — родительские материалы

| Поле | Тип |
|---|---|
| id | uuid PK |
| child_id | uuid FK→materials not null |
| parent_id | uuid FK→materials not null |
| parent_version_id | uuid FK→material_versions not null — версия родителя на момент привязки (треб. 27) |
| created_by / created_at | |

- `unique (child_id)` — не более одного родителя (решение §16 п. 5).
- Перепривязка = update `parent_version_id` (новая актуальная версия родителя); отвязка = delete строки. Обе — операции редактирования (ВЕРС-4).

## 8. chunks — чанки (текст + FTS + вектор)

| Поле | Тип | Описание |
|---|---|---|
| id | uuid PK | |
| material_id | uuid FK→materials not null | денормализация для фильтров |
| version_id | uuid FK→material_versions not null | чанки принадлежат версии |
| chunk_index | integer not null | порядковый номер в версии |
| parent_index | integer, nullable | для parent-child чанкеров |
| chunker_name / chunker_version | text not null | кто и чем сгенерирован (ЧНК-3) |
| text | text not null | |
| metadata | jsonb | лист, диапазон строк, заголовки и т.п. |
| tsv | tsvector | FTS-индекс (GIN); конфигурации ru/en — отдельные колонки `tsv_ru`, `tsv_en` (ПСК-5); названия/описания — в отдельных FTS-колонках (§8.1) |
| embedding | vector(dim) not null | pgvector; размерность — от модели эмбеддингов |

- `unique (version_id, chunk_index, chunker_name)` — детерминированность; замена чанков версии — атомарно `delete … where version_id = …` + `insert` в одной транзакции (НФТ-9).
- Индекс: `CREATE INDEX ON chunks USING hnsw (embedding halfvec_ops)`; фильтрация по правам/атрибутам — SQL JOIN (§14).
- При смене эмбеддинг-модели — полная переиндексация (пересоздание колонки/индекса под новую размерность, РАГ-3).

## 9. status_journal — журнал переходов статусов (append-only)

| Поле | Тип |
|---|---|
| id | uuid PK |
| material_id | uuid FK→materials not null |
| version_id | uuid FK→material_versions not null |
| from_status / to_status | enum'ы |
| actor_id | uuid FK→users not null |
| request_id | uuid, nullable — Idempotency-Key клиента |
| created_at | timestamptz not null |

```sql
-- Идемпотентность переходов (НФТ-9): ретрай с тем же request_id отсекается индексом,
-- повтор без ключа — машиной состояний (переход недопустим из текущего статуса).
CREATE UNIQUE INDEX uq_status_journal_request
  ON status_journal (request_id) WHERE request_id IS NOT NULL;
```

- Строки **никогда не изменяются и не удаляются**; текущий статус материала согласован с последней записью журнала (СТАТ-2, СТАТ-3).

## 10. notifications — уведомления

| Таблица | Поля | Назначение |
|---|---|---|
| notification_events | id, code, title | справочник событий (УВЕД-3) |
| notification_subscriptions | event_code, role, channel | настройка «событие × роль → канал» (УВЕД-2, системная настройка) |
| notification_deliveries | id, event_id, recipient_id, channel, status, sent_at, idempotency_key | `unique (idempotency_key)`; ретрай доставки не дублирует письмо (НФТ-9) |

- `idempotency_key` доставки = детерминированный (`event_id`, `recipient_id`).

## 11. settings — настройки системы (в БД, не env)

| Поле | Тип |
|---|---|
| key | text PK |
| value | jsonb |
| updated_by / updated_at | |

- Примеры: `upload.max_size_mb` = 50 (НФТ-5), `embedding.{base_url,model,dims}`, `llm.{base_url,model}`, `fts.languages`, `default_chunker.{name,params}` (ЧНК-5), события уведомлений.
- **Не секреты.** Секреты (SMTP-креденшелы, api_key моделей, ключи Silo/Valkey/Keycloak) — только env (НФТ-5).

## 12. chunker_registry — реестр чанкеров

| Поле | Тип |
|---|---|
| name | text PK |
| code_hash | text — hash файла плагина (версия кода) |
| builtin | boolean — встроенный или плагин |
| params_schema | jsonb — схема параметров для админки |
| is_loaded | boolean / error text — результат последней загрузки (ЧНК-8) |

- Плагины — файлы в `plugins/chunkers/`, динамическая загрузка `importlib` воркером; эндпоинт «перечитать плагины» обновляет реестр без пересборки (ЧНК-3).

## 13. jobs — задачи пайплайна (прогресс и ошибки)

| Поле | Тип |
|---|---|
| id | uuid PK |
| material_id / version_id | uuid |
| step | enum('av','extract','chunk','embed','preview') |
| status | enum('pending','running','done','failed') |
| attempts | integer |
| error | text |
| updated_at | timestamptz |

- Ключ идемпотентности шага: `(version_id, step)` — `unique`; повтор шага переписывает результат (НФТ-9).
- Реконсилятор: задачи `running` без прогресса дольше N минут → перевыставление (§13.1).
- Очередь — Valkey (Celery); задача в брокере — «будильник», источник истины — эти таблицы.

## 14. audit_log — журнал аудита (append-only)

| Поле | Тип |
|---|---|
| id | bigserial PK |
| at | timestamptz not null |
| actor_id | uuid (nullable для системных событий) |
| action | text — код действия (`material.version.upload`, `status.change`, `role.grant`, `file.download`, `plugin.reload`, …) |
| object_type / object_id | text/uuid |
| details | jsonb — изменения до/после |
| request_id | uuid |

- Записи не редактируются и не удаляются через API (НФТ-1); на уровне БД — запрет UPDATE/DELETE правами приложения.
- Прямой доступ к файлам идёт через API (ПРС-1), поэтому `file.download` фиксируется гарантированно.

## 15. Ключи идемпотентности — сводка

| Операция | Ключ | Механизм |
|---|---|---|
| Загрузка файла → новая версия | `Idempotency-Key` клиента (обязателен) + `files (sha256, size)` | повтор запроса → исходный ответ; дедупликация объекта |
| Изменяющие операции API | `Idempotency-Key` (фронт всегда; интеграции — рекомендован) | кэш «ключ → ответ» в Valkey, TTL 24 ч |
| Шаги пайплайна | `jobs (version_id, step)` unique | шаг переписывает результат |
| Чанки версии | `unique (version_id, chunk_index, chunker_name)` | атомарная замена |
| Вектора | upsert по `chunks.id` (+ модель) | идемпотентный upsert |
| Переходы статусов | `status_journal (request_id)` unique + машина состояний | ретрай → исходный ответ; повтор без ключа → 409 |
| Доставка уведомлений | `notification_deliveries (idempotency_key)` | одно письмо на событие/получателя |
| Перемещение материала/группы | проверка прав + уникальность имён + проверка циклов | отказ вместо дубля |

## 16. Правила миграций (Alembic)

1. Каждое изменение схемы — отдельная миграция, применяемая строго вперёд (no down-migrations в проде; откат — новой миграцией).
2. Индексы pgvector/HNSW и изменения колонок векторов — только в сопровождении переиндексации (ЧНК-9): миграция схемы + фоновая задача пересчёта.
3. Запрещено удалять/переименовывать колонки, на которые ссылаются аудит-записи (details.jsonb), без сохранения совместимости чтения.
4. Миграции применяются автоматически при деплое; две активные версии кода (rolling) должны работать на одной промежуточной схеме — изменения добавляются аддитивно.

## 17. Что запрещено удалять физически

- `users`, `groups`, `materials`, `material_versions`, `files`, `status_journal`, `audit_log` — только soft-delete/архивация; физическая очистка — отдельной процедурой администратора вне обычного потока (НФТ-10).
- `chunks` — исключение: чанки неактуальных версий удаляются при вытеснении (индексируется только актуальная версия, ВЕРС-3); история версий при этом сохраняется в `material_versions`.
