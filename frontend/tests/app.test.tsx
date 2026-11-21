import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from '../src/app/App'

// jsdom: fetch для дерева групп — заглушка (главный экран рендерится и без данных)
vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => [] }))

describe('App (Этап 1)', () => {
  it('рендерит главный экран с шапкой и поиском', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )
    expect(screen.getByText('База знаний')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Поиск по базе…')).toBeInTheDocument()
  })
})
