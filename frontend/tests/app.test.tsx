import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from '../src/app/App'
import { ThemeProvider, ThemeToggle } from '../src/shared/theme'

// jsdom: fetch для дерева групп — заглушка (главный экран рендерится и без данных)
vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => [] }))

describe('App (Этап 1)', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('рендерит главный экран с шапкой и поиском', () => {
    localStorage.setItem('kb_access_token', 't') // аутентифицированы (RequireAuth)
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )
    expect(screen.getByText('База знаний')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Поиск по базе…')).toBeInTheDocument()
  })

  it('тема: переключение сохраняется в localStorage (dark → light)', () => {
    localStorage.setItem('kb_theme', 'dark')
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    )
    const btn = screen.getByRole('button', { name: 'Переключить тему' })
    fireEvent.click(btn)
    expect(localStorage.getItem('kb_theme')).toBe('light')
    fireEvent.click(btn)
    expect(localStorage.getItem('kb_theme')).toBe('dark')
  })
})
