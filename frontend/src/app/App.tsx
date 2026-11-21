import { ConfigProvider, theme as antdTheme } from 'antd'
import ruRU from 'antd/locale/ru_RU'
import { useEffect, type ReactElement, type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { isAuthenticated } from '../shared/api/auth'
import { ThemeProvider, useThemeMode } from '../shared/theme'
import LoginPage from '../pages/LoginPage'
import MainPage from '../pages/MainPage'
import MaterialPage from '../pages/MaterialPage'
import MaterialFormPage from '../pages/MaterialFormPage'
import SearchPage from '../pages/SearchPage'

/**
 * Маршруты Этапа 1 (ui-ux §1): главный экран (дерево+материалы), карточка,
 * формы создания/версий, поиск; /login — вход через Keycloak (АУТ-1).
 * Тема — dark/light через algorithm antd 5, выбор в localStorage (shared/theme).
 */

function RequireAuth({ children }: { children: ReactElement }) {
  return isAuthenticated() ? children : <Navigate to="/login" replace />
}

/** Фон страницы под тему (token от алгоритма; компонент внутри ConfigProvider). */
function BodyBackground() {
  const { token } = antdTheme.useToken()
  useEffect(() => {
    document.body.style.background = token.colorBgLayout
    document.body.style.color = token.colorText
  }, [token])
  return null
}

function ThemedApp({ children }: { children: ReactNode }) {
  const { mode } = useThemeMode()
  return (
    <ConfigProvider
      locale={ruRU}
      theme={{ algorithm: mode === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm }}
    >
      <BodyBackground />
      {children}
    </ConfigProvider>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <ThemedApp>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/"
            element={
              <RequireAuth>
                <MainPage />
              </RequireAuth>
            }
          >
            <Route path="groups/:gid/new-material" element={<MaterialFormPage />} />
            <Route path="materials/:id" element={<MaterialPage />} />
            <Route path="materials/:id/edit" element={<MaterialFormPage />} />
            <Route path="search" element={<SearchPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </ThemedApp>
    </ThemeProvider>
  )
}
