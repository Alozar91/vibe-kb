import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './app/App'

// basename=/know — deployment.md §1.1 (публичный адрес https://merch-vibe.ru/know)
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter basename="/know">
      <App />
    </BrowserRouter>
  </StrictMode>,
)
