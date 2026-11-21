/**
 * Dev-аутентификация: на старте токен вводится вручную или подставляется тестовый.
 * Этап 1 (АУТ): редирект на Keycloak (Authorization Code + PKCE) — ключевой экран /login.
 * Локально Keycloak dev-realm недоступен → допускаем dev-токен из localStorage.
 */

import { setToken } from './client'

const KEY = 'kb_access_token'

export function initAuthFromStorage(): boolean {
  const t = localStorage.getItem(KEY)
  if (t) {
    setToken(t)
    return true
  }
  return false
}

/** Dev-вход: токен вставляет пользователь (получен из Keycloak напрямую). */
export function devLogin(token: string): void {
  localStorage.setItem(KEY, token)
  setToken(token)
}

export function logout(): void {
  localStorage.removeItem(KEY)
  location.reload()
}

export function isAuthenticated(): boolean {
  return Boolean(localStorage.getItem(KEY))
}
