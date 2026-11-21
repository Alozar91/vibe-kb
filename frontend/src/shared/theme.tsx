import { MoonOutlined, SunOutlined } from '@ant-design/icons'
import { Button, Tooltip } from 'antd'
import { createContext, useContext, useState, type ReactNode } from 'react'

/** Тема SPA: antd-алгоритм (dark/light) + выбор в localStorage («хранить на фронтенде»). */

export type ThemeMode = 'light' | 'dark'

const KEY = 'kb_theme'

interface ThemeContextValue {
  mode: ThemeMode
  toggle: () => void
}

const ThemeContext = createContext<ThemeContextValue>({ mode: 'light', toggle: () => undefined })

function initialMode(): ThemeMode {
  try {
    const stored = localStorage.getItem(KEY)
    if (stored === 'dark' || stored === 'light') return stored
  } catch {
    // приватный режим/недоступный localStorage — системная тема
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(initialMode)

  const toggle = () =>
    setMode((prev) => {
      const next: ThemeMode = prev === 'dark' ? 'light' : 'dark'
      try {
        localStorage.setItem(KEY, next)
      } catch {
        // сохранение темы не критично
      }
      return next
    })

  return <ThemeContext.Provider value={{ mode, toggle }}>{children}</ThemeContext.Provider>
}

export const useThemeMode = (): ThemeContextValue => useContext(ThemeContext)

/** Кнопка-переключатель (луна/солнце) — в шапке и на экране входа. */
export function ThemeToggle() {
  const { mode, toggle } = useThemeMode()
  return (
    <Tooltip title={mode === 'dark' ? 'Светлая тема' : 'Тёмная тема'}>
      <Button
        type="text"
        aria-label="Переключить тему"
        icon={mode === 'dark' ? <SunOutlined /> : <MoonOutlined />}
        onClick={toggle}
      />
    </Tooltip>
  )
}
