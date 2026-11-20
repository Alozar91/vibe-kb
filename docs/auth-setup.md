# Настройка аутентификации: Keycloak + AD

- **Статус:** рабочий документ (v0.2, 2026-11-20)
- **Основа:** §4 концепции (АУТ-1…АУТ-6 в ТЗ). Документ двухадресный: часть 1 — задачи для **AD-администраторов** (передать им заранее!), часть 2 — настройка **Keycloak**, часть 3 — чек-лист приёмки.
- **Важно (2026-11-20):** корпоративной сети/AD пока **нет**. На старте работает только вход локальных пользователей Keycloak (АУТ-3). Раздел 1 (задачи AD) и настройка LDAP/Kerberos (§2.3, §2.4) — **отложены до появления AD**; публичный адрес — `https://merch-vibe.ru/know`, SPN на будущее — `HTTP/merch-vibe.ru`.

---

## 1. Требования к инфраструктуре AD (для AD-администраторов)

| № | Задача | Детали |
|---|---|---|
| AD-1 | Создать service account для LDAP-подключения Keycloak | read-only bind-аккаунт, например `svc-keycloak-ldap`; права — чтение дерева пользователей |
| AD-2 | Зарегистрировать SPN для сайта КБ | `setspn -S HTTP/merch-vibe.ru svc-keycloak-kerberos` (hostname — `merch-vibe.ru`; путь `/know` на SPN не влияет; CNAME должен совпадать) |
| AD-3 | Экспортировать keytab для этого SPN | `ktpass -out kb-http.keytab -princ HTTP/merch-vibe.ru@<REALM> -mapUser svc-keycloak-kerberos +rndPass …`; keytab передаётся на сервер Keycloak по защищённому каналу |
| AD-4 | Синхронизация времени | Kerberos чувствителен к рассинхронизации (>5 мин = отказ) — сервер Keycloak в доменном времени |
| AD-5 | Параметры LDAP для federation | адрес(а) контроллеров домена, базовый DN пользователей, атрибуты: логин (sAMAccountName), email, отображаемое имя, `userPrincipalName` |
| AD-6 | Групповые политики браузеров на рабочих станциях | Edge/IE: `merch-vibe.ru` — в зону «Локальная интрасеть»; Chrome: политика `AuthServerAllowlist = merch-vibe.ru` (и, если потребуется делегирование, `AuthNegotiateDelegateAllowlist`); Firefox — `network.negotiate-auth.trusted-uris` |
| AD-7 | Согласовать процесс блокировки учётных записей | при увольнении — disable в AD (АУТ-4); список локальных (не доменных) пользователей ведёт админ Keycloak |

- Без AD-6 браузер покажет обычный экран логина — это штатный fallback (АУТ-2 выполнится только после настройки политик).
- TLS-сертификат приёмочного сервера — со стороны владельца сервера (НФТ-3).

## 2. Настройка Keycloak

### 2.1 Realm и общее

1. Создать realm `corp-kb`.
2. Секреты: bind-пароль LDAP — через **Keycloak Vault** (файловый vault: `KC_VAULT=file`, `KC_VAULT_FILE_DIR`; в поле Bind Credential провайдера — ссылка `${vault.ldap_bind_password}`); keytab — смонтированный файл, путь задаётся в конфигурации Kerberos-провайдера. В экспортируемом JSON конфигурации realm'а секретов быть не должно (НФТ-5).
3. Политики паролей — только для локальных пользователей (АУТ-3); доменные проверяются в AD.

### 2.2 Клиенты

| Client | Тип | Назначение | Настройки |
|---|---|---|---|
| `kb-web` | public | SPA (React) | Authorization Code + PKCE; redirect `https://merch-vibe.ru/know/*`; **Direct Access Grants OFF** |
| `kb-rag` | confidential (или public+PKCE) | RAG API для интеграций и скриптов | client credentials разрешён для service accounts (АУТ-6) |
| `kb-mcp` | confidential | MCP-сервер | OAuth для агентов (authorization code) + service accounts для техинтеграций |

- На каждом клиенте — политики «кто может получить токен»: `kb-web` — только интерактивные пользователи; `kb-rag`/`kb-mcp` — интерактивные пользователи ИЛИ service accounts по необходимости (решение §11.3).
- Audience-маппинги: токены содержат `aud` соответствующего клиента; API проверяет свой `aud` (АУТ-5).

### 2.3 LDAP User Federation

1. User Federation → Add LDAP: vendor `Active Directory`, connection URL(AD-5), bind DN (AD-1), bind password — vault-ссылка `${vault.ldap_bind_password}` (см. 2.1).
2. Sync: `Import users` on; periodic full/changed sync — по согласованию (или доверяться импорту при первом входе, JIT).
3. Mappers: `username` ← sAMAccountName, `email` ← mail, `firstName/lastName`, ключевой — **Kerberos principal attribute = `userPrincipalName`** (связка для АУТ-2).
4. Edit mode: `READONLY` (пользователи и пароли управляются в AD).
5. Проверка: `Test connection`, `Sync all users`, найти тестового пользователя.

### 2.4 Kerberos (SPNEGO) — отложено до появления AD

1. В LDAP-провайдере: **Allow Kerberos authentication = ON**; Kerberos realm `<домен компании>`; Server Principal `HTTP/merch-vibe.ru@<REALM>`; Keytab — путь до смонтированного файла (например, `/opt/keycloak/conf/kb-http.keytab`, AD-3); путь задаётся в этом поле конфигурации, не через env; `debug` — на время приёмки.
2. Authentication → Flows → **browser**: Kerberos = **alternative** (пользователи без Kerberos откатятся на пароль; штатное поведение Keycloak).
3. Сопоставление principal → LDAP-пользователь — по `userPrincipalName` (2.3.3): `john@<REALM>` → пользователь `john` в LDAP.
4. `/etc/krb5.conf` на сервере Keycloak: realm компании, KDC контроллеры (AD-5).

### 2.5 Локальные пользователи и service accounts

- Локальные пользователи создаются вручную в realm (АУТ-3); для них действует политика паролей realm; блокировка — флагом `enabled=false`.
- Service accounts: `Clients → kb-rag/kb-mcp → Service accounts enabled`; учётке service account выдаются роли в группах **через интерфейс КБ**, как обычному пользователю (§4 концепции) — КБ не читает права из Keycloak.

### 2.6 Токены и протоколы

- Подпись RS256; JWKS: `https://<keycloak>/realms/corp-kb/protocol/openid-connect/certs`.
- Access token TTL: 5–15 мин; refresh для SPA (silent renew, АУТ/§4).
- В `kb-web` включить logout (front-channel/back-channel).

## 3. Жизненный цикл пользователей (сводка)

| Событие | Механизм |
|---|---|
| Первый вход через LDAP/Kerberos | JIT: пользователь создаётся в realm и в БД КБ (АУТ-1) |
| Вход локального пользователя | локальная проверка пароля в realm (АУТ-3) |
| Уход из компании | disable в AD → вход прекращается; роли/авторство сохраняются (АУТ-4) |
| Уход локального пользователя/подрядчика | блокировка админом Keycloak (АУТ-3) |
| Смена ФИО/почты в AD | подхватывается при следующем входе (синхронизация профиля) |

## 4. Чек-лист приёмки аутентификации

- [ ] Вход паролем доменного пользователя (АУТ-1) — успех, пользователь появился в КБ.
- [ ] Вход паролем с неверным паролем — отказ.
- [ ] Kerberos: доменная машина + настроенный браузер → вход без пароля (АУТ-2); пользователь тот же, что в АУТ-1.
- [ ] Kerberos снаружи домена (или не доменная машина) → обычный экран логина, пароль работает.
- [ ] Локальный пользователь: создание, вход, блокировка админом, повторный вход — отказ (АУТ-3).
- [ ] Disable учётки в AD → вход отказ; материалы и роли сохранены (АУТ-4).
- [ ] Токен `kb-web` не выдаётся service account'у; токен `kb-rag` — выдаётся по client credentials (АУТ-6).
- [ ] Запрос к API без токена/с чужим `aud` → 401 (АУТ-5).
- [ ] Сессия SPA: refresh работает, logout завершает сеанс в Keycloak.

## 5. Переменные окружения (аутентификация)

| Переменная | Назначение |
|---|---|
| `KC_DB_URL`, `KC_DB_USERNAME`, `KC_DB_PASSWORD` | БД Keycloak (переменные Keycloak, префикс `KC_`) |
| `KC_HOSTNAME`, `KC_HTTPS_CERTIFICATE_*` | hostname/TLS realm'а |
| `KC_LDAP_BIND_DN`, `KC_LDAP_BIND_PASSWORD` | bind-аккаунт (секрет) |
| `KC_KERBEROS_KEYTAB_PATH` | путь к keytab (секрет) |
| `KB_API_KEYCLOAK_ISSUER` | `https://<keycloak>/realms/corp-kb` (переменные приложения КБ, префикс `KB_`) |
| `KB_API_KEYCLOAK_AUDIENCES` | ожидаемые `aud` (`kb-rag`, `kb-mcp`, …) |
| `KB_API_JWKS_CACHE_TTL` | TTL кэша JWKS |

- Префиксы неймспейсов: `KC_*` — конфигурация сервера Keycloak; `KB_*` — конфигурация приложения КБ.

> Названия переменных — целевые; финальные имена фиксируются в `docs/deployment.md` при сборке Этапа 0.
