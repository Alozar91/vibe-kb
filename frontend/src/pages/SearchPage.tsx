import { useEffect, useState } from 'react'
import { Input, Select, List, Card, Tag, Spin, message } from 'antd'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { searchApi, type SearchHit } from '../shared/api/client'


function errMsg(e: unknown): string {
  if (e && typeof e === "object" && "detail" in e && typeof (e as { detail?: unknown }).detail === "string") {
    return (e as { detail: string }).detail
  }
  if (e instanceof Error) return e.message
  return "Ошибка"
}


const MODES = [
  { value: 'fulltext', label: 'Полнотекстовый' },
  { value: 'vector', label: 'Векторный' },
  { value: 'hybrid', label: 'Гибридный' },
  { value: 'attributes', label: 'По атрибутам' },
]

export default function SearchPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [query, setQuery] = useState(params.get('q') ?? '')
  const [mode, setMode] = useState('hybrid')
  const [hits, setHits] = useState<SearchHit[]>([])
  const [loading, setLoading] = useState(false)

  // Начальный запуск по ?q из URL — через ленивую инициализацию состояния, не в эффекте
  const [initialQuery] = useState(() => params.get('q') ?? '')

  const run = async (q: string, m: string) => {
    if (!q.trim()) return
    setLoading(true)
    try {
      const out = await searchApi.query({ query: q, mode: m, top_k: 50 })
      setHits(out.results)
    } catch (e: unknown) {
      message.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    // только для initial-URL: единичный запуск при монтировании
    const controller = new AbortController()
    const initial = async () => {
      if (!initialQuery.trim()) return
      setLoading(true)
      try {
        const out = await searchApi.query({ query: initialQuery, mode, top_k: 50 })
        setHits(out.results)
      } catch (e: unknown) {
        message.error(errMsg(e))
      } finally {
        setLoading(false)
      }
    }
    void initial()
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div style={{ maxWidth: 900 }}>
      <Input.Search
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onSearch={(q) => run(q, mode)}
        enterButton="Искать"
        size="large"
        style={{ marginBottom: 12 }}
      />
      <Select
        value={mode}
        onChange={(m) => { setMode(m); if (query) run(query, m) }}
        options={MODES}
        style={{ width: 220, marginBottom: 16 }}
      />
      {loading && <Spin />}
      <List
        dataSource={hits}
        renderItem={(h) => (
          <Card size="small" style={{ marginBottom: 8 }}>
            <Tag>{h.type === 'group' ? 'Группа' : 'Материал'}</Tag>
            <a
              onClick={() =>
                h.type === 'material'
                  ? navigate(`/materials/${h.material_id}`)
                  : navigate('/')
              }
            >
              <b>{h.name}</b>
            </a>
            {h.snippet && <p style={{ color: '#666', marginTop: 8 }}>{h.snippet}…</p>}
            <span style={{ color: '#999', fontSize: 12 }}>score: {h.score.toFixed(4)}</span>
          </Card>
        )}
      />
      {!loading && hits.length === 0 && <p>Нет результатов.</p>}
    </div>
  )
}
