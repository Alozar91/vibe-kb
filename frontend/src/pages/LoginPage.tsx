import { useState } from 'react'
import { Button, Card, Input, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { devLogin, login } from '../shared/api/auth'
import { ThemeToggle } from '../shared/theme'

/**
 * Экран входа (АУТ-1): Keycloak Authorization Code + PKCE.
 * Вставка токена — dev-fallback (auth.ts), для curl-сценариев и отладки.
 */
export default function LoginPage() {
  const navigate = useNavigate()
  const [token, setToken] = useState('')

  return (
    <div style={{ display: 'grid', placeItems: 'center', minHeight: '80vh', position: 'relative' }}>
      <div style={{ position: 'absolute', top: 16, right: 16 }}>
        <ThemeToggle />
      </div>
      <Card title="Вход в базу знаний" style={{ width: 440 }}>
        <Typography.Paragraph type="secondary">
          Корпоративная аутентификация (Keycloak, realm «corp-kb»). Используйте учётную запись
          домена или локальную тестовую.
        </Typography.Paragraph>
        <Button type="primary" block onClick={() => login()}>
          Войти через Keycloak
        </Button>

        <Typography.Paragraph style={{ marginTop: 24, marginBottom: 4 }} type="secondary">
          Dev-режим: вставить access_token вручную
        </Typography.Paragraph>
        <Input.TextArea
          rows={3}
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="eyJhbGciOi..."
        />
        <Button
          block
          style={{ marginTop: 8 }}
          disabled={!token.trim()}
          onClick={() => {
            devLogin(token.trim())
            navigate('/')
          }}
        >
          Войти с токеном
        </Button>
      </Card>
    </div>
  )
}
