import { useEffect, useState } from 'react'
import { Descriptions, Tabs, Tag, Button, Popconfirm, Table, message, Space, List } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { materialsApi, type Material, type Version } from '../shared/api/client'


function errMsg(e: unknown): string {
  if (e && typeof e === "object" && "detail" in e && typeof (e as { detail?: unknown }).detail === "string") {
    return (e as { detail: string }).detail
  }
  if (e instanceof Error) return e.message
  return "Ошибка"
}


// Допустимые переходы (СТАТ-2) — источник: машина состояний бекенда; кнопки только валидные (ui-ux §3)
const TRANSITIONS: Record<string, { to: string; label: string; danger?: boolean }[]> = {
  draft: [{ to: 'on_review', label: 'На проверку' }, { to: 'deleted', label: 'Удалить', danger: true }],
  on_review: [
    { to: 'confirmed', label: 'Подтвердить' },
    { to: 'draft', label: 'Вернуть на доработку', danger: true },
    { to: 'archived', label: 'В архив' },
  ],
  confirmed: [{ to: 'draft', label: 'В черновик' }, { to: 'archived', label: 'В архив' }],
  archived: [],
  deleted: [],
}

const STATUS_LABELS: Record<string, string> = {
  draft: 'Черновик',
  on_review: 'На проверке',
  confirmed: 'Подтверждён',
  archived: 'Архив',
  deleted: 'Удалён',
}

const STATUS_COLORS: Record<string, string> = {
  draft: 'default',
  on_review: 'processing',
  confirmed: 'success',
  archived: 'warning',
  deleted: 'error',
}

export default function MaterialPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [material, setMaterial] = useState<Material | null>(null)
  const [versions, setVersions] = useState<Version[]>([])

  const load = () => {
    if (!id) return
    materialsApi.get(id).then(setMaterial).catch((e) => message.error(errMsg(e)))
    materialsApi.versions(id).then(setVersions).catch(() => {})
  }

  useEffect(load, [id])

  const transition = async (to: string) => {
    if (!id) return
    try {
      const requestId = crypto.randomUUID()
      await materialsApi.transitions(id, to, requestId)
      message.success('Статус изменён')
      load()
    } catch (e: unknown) {
      message.error(errMsg(e))
    }
  }

  if (!material) return <p>Загрузка…</p>

  const current = versions.find((v) => v.id === material.current_version_id)

  return (
    <div>
      <h2>{material.name}</h2>
      <Space style={{ marginBottom: 16 }}>
        <Tag color={STATUS_COLORS[material.status]}>{STATUS_LABELS[material.status]}</Tag>
        <Button onClick={() => navigate(-1)}>Назад</Button>
        <Button onClick={() => navigate(`/materials/${id}/edit`)}>Новая версия</Button>
      </Space>

      {(TRANSITIONS[material.status] ?? []).map((t) => (
        <Popconfirm
          key={t.to}
          title={t.label + '?'}
          description={t.danger ? 'Восстановление невозможно' : undefined}
          onConfirm={() => transition(t.to)}
        >
          <Button danger={t.danger} style={{ marginRight: 8 }}>
            {t.label}
          </Button>
        </Popconfirm>
      ))}

      <Tabs
        items={[
          {
            key: 'info',
            label: 'Информация',
            children: current && (
              <Descriptions column={1} bordered size="small">
                <Descriptions.Item label="Описание">{current.description ?? '—'}</Descriptions.Item>
                <Descriptions.Item label="Внешние ссылки">
                  {current.external_links?.length ? (
                    <List
                      size="small"
                      dataSource={current.external_links}
                      renderItem={(l) => (
                        <List.Item>
                          <a href={l.url} target="_blank" rel="noreferrer">{l.label}</a>
                        </List.Item>
                      )}
                    />
                  ) : '—'}
                </Descriptions.Item>
                <Descriptions.Item label="Атрибуты">
                  <pre style={{ margin: 0 }}>{JSON.stringify(current.attributes ?? {}, null, 2)}</pre>
                </Descriptions.Item>
                <Descriptions.Item label="Антивирус">
                  {current.av_status === 'clean' || current.av_status === 'skipped_stub' ? (
                    <Button href={`/api/v1/versions/${current.id}/file`} target="_blank">
                      Скачать файл
                    </Button>
                  ) : (
                    <Button disabled title="Проверка на вирусы не завершена (НФТ-4)">
                      Скачать (скан не завершён)
                    </Button>
                  )}
                </Descriptions.Item>
              </Descriptions>
            ),
          },
          {
            key: 'versions',
            label: `Версии (${versions.length})`,
            children: (
              <Table<Version>
                rowKey="id"
                dataSource={versions}
                pagination={false}
                columns={[
                  { title: '№', dataIndex: 'version_no', width: 60 },
                  { title: 'Комментарий', dataIndex: 'change_comment' },
                  { title: 'Дата', dataIndex: 'created_at' },
                  {
                    title: 'Файл',
                    render: (_, v) =>
                      v.av_status === 'clean' || v.av_status === 'skipped_stub' ? (
                        <a href={`/api/v1/versions/${v.id}/file`} target="_blank">скачать</a>
                      ) : 'скан…',
                  },
                ]}
              />
            ),
          },
        ]}
      />
    </div>
  )
}
