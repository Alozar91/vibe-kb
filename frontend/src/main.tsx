import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './app/App'
import { initAuth } from './shared/api/auth'

// basename=/know — deployment.md §1.1 (публичный адрес https://merch-vibe.ru/know).
// initAuth ДО рендера: обмен ?code=... на токен (АУТ-2) и восстановление сессии,
// чтобы первый запрос к API уже нёс Bearer.
void initAuth().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <BrowserRouter basename="/know">
        <App />
      </BrowserRouter>
    </StrictMode>,
  )
})
