/**
 * Аутентификация SPA (АУТ-1/2): Keycloak Authorization Code + PKCE (public-клиент kb-web).
 * Экран /login; dev-вход вставкой токена остаётся fallback'ом (curl-тесты, отладка).
 *
 * Путь к Keycloak — /auth (nginx проксирует на keycloak:8080/auth; в dev — vite proxy).
 * Issuer токенов (http://localhost:8899/realms/corp-kb) использует backend при проверке —
 * браузеру он не нужен: браузер работает по путям, не по issuer.
 */

import { setToken } from './client'

const KEY = 'kb_access_token'
const REALM = 'corp-kb'
const CLIENT_ID = 'kb-web'

const kcBase = (): string => `${window.location.origin}/auth`
const realmUrl = (): string => `${kcBase()}/realms/${REALM}`
const redirectUri = (): string => `${window.location.origin}${import.meta.env.BASE_URL}`

function b64url(buf: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(buf)))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
}

/** PKCE-пара (RFC 7636): verifier + S256 challenge. */
async function pkcePair(): Promise<{ verifier: string; challenge: string }> {
  const verifier = b64url(crypto.getRandomValues(new Uint8Array(32)).buffer)
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
  return { verifier, challenge: b64url(digest) }
}

/** Начать вход: сохранить PKCE-пару и state, редирект на Keycloak authorize. */
export function login(): void {
  void (async () => {
    const { verifier, challenge } = await pkcePair()
    const state = b64url(crypto.getRandomValues(new Uint8Array(16)).buffer)
    sessionStorage.setItem('kb_pkce_verifier', verifier)
    sessionStorage.setItem('kb_pkce_state', state)
    const params = new URLSearchParams({
      response_type: 'code',
      client_id: CLIENT_ID,
      scope: 'openid',
      redirect_uri: redirectUri(),
      state,
      code_challenge: challenge,
      code_challenge_method: 'S256',
    })
    window.location.assign(`${realmUrl()}/protocol/openid-connect/auth?${params}`)
  })()
}

/** Обработать возврат с ?code=... (после логина в Keycloak): обменять код на токен. */
async function handleRedirect(): Promise<void> {
  const url = new URL(window.location.href)
  const code = url.searchParams.get('code')
  if (!code) return

  const state = url.searchParams.get('state')
  const expected = sessionStorage.getItem('kb_pkce_state')
  const verifier = sessionStorage.getItem('kb_pkce_verifier')
  sessionStorage.removeItem('kb_pkce_state')
  sessionStorage.removeItem('kb_pkce_verifier')
  if (!state || state !== expected || !verifier) return // защита от CSRF/повтора

  const resp = await fetch(`${realmUrl()}/protocol/openid-connect/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: CLIENT_ID,
      code,
      redirect_uri: redirectUri(),
      code_verifier: verifier,
    }),
  })
  if (!resp.ok) return // неудачный обмен — остаёмся не аутентифицированы
  const data = (await resp.json()) as { access_token?: string }
  if (!data.access_token) return

  localStorage.setItem(KEY, data.access_token)
  setToken(data.access_token)
  // чистим адрес от code/state — пользователь видит чистый /know/
  window.history.replaceState({}, '', redirectUri())
}

/** Инициализация при старте приложения (до первого запроса к API). */
export async function initAuth(): Promise<void> {
  await handleRedirect().catch(() => undefined)
  const t = localStorage.getItem(KEY)
  if (t) setToken(t)
}

/** Dev-вход: токен вставляет пользователь (получен из Keycloak напрямую). */
export function devLogin(token: string): void {
  localStorage.setItem(KEY, token)
  setToken(token)
}

export function logout(): void {
  localStorage.removeItem(KEY)
  // TODO(АУТ-6): server-side end-session (нужен id_token_hint и post_logout redirect в realm)
  window.location.href = `${import.meta.env.BASE_URL}login`
}

export function isAuthenticated(): boolean {
  return Boolean(localStorage.getItem(KEY))
}
