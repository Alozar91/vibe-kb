import { ConfigProvider } from 'antd'
import ruRU from 'antd/locale/ru_RU'
import { Navigate, Route, Routes } from 'react-router-dom'
import MainPage from '../pages/MainPage'
import MaterialPage from '../pages/MaterialPage'
import MaterialFormPage from '../pages/MaterialFormPage'
import SearchPage from '../pages/SearchPage'

/**
 * Маршруты Этапа 1 (ui-ux §1): главный экран (дерево+материалы), карточка,
 * формы создания/версий, поиск. Роутер (BrowserRouter) подключается в main.tsx.
 */
export default function App() {
  return (
    <ConfigProvider locale={ruRU}>
      <Routes>
        <Route path="/" element={<MainPage />}>
          <Route path="groups/:gid/new-material" element={<MaterialFormPage />} />
          <Route path="materials/:id" element={<MaterialPage />} />
          <Route path="materials/:id/edit" element={<MaterialFormPage />} />
          <Route path="search" element={<SearchPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ConfigProvider>
  )
}
