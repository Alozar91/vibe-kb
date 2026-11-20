import { ConfigProvider } from 'antd'
import ruRU from 'antd/locale/ru_RU'
import { Navigate, Route, Routes } from 'react-router-dom'

/**
 * Корневой компонент: Ant Design 5 (ru) + маршруты.
 * Роутер (BrowserRouter) подключается в main.tsx; в тестах — MemoryRouter.
 */
export default function App() {
  return (
    <ConfigProvider locale={ruRU}>
      <Routes>
        <Route path="/" element={<main style={{ padding: 24 }}>
          <h1>Корпоративная база знаний</h1>
          <p>Каркас Этапа 0. Экраны — с Этапа 1 (см. docs/ui-ux.md).</p>
        </main>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ConfigProvider>
  )
}
