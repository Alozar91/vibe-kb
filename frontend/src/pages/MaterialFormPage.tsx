import { Form, Input, Upload, Button, message, Space } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { materialsApi } from '../shared/api/client'
import { useState } from 'react'


function errMsg(e: unknown): string {
  if (e && typeof e === "object" && "detail" in e && typeof (e as { detail?: unknown }).detail === "string") {
    return (e as { detail: string }).detail
  }
  if (e instanceof Error) return e.message
  return "Ошибка"
}


/** Создание/новая версия материала (ui-ux §1 экран 4): файл drag&drop + метаданные. */
export default function MaterialFormPage() {
  const { gid, id } = useParams<{ gid?: string; id?: string }>()
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [saving, setSaving] = useState(false)

  interface FormValues {
    name?: string
    description?: string
    change_comment: string
    external_links?: (string | null)[]
  }

  const onSubmit = async (values: FormValues) => {
    setSaving(true)
    try {
      const form = new FormData()
      form.append('change_comment', values.change_comment)
      if (!id) form.append('name', values.name ?? '')
      if (values.description) form.append('description', values.description)
      if (values.external_links?.length) {
        form.append('external_links', JSON.stringify(
          values.external_links.filter((l): l is string => Boolean(l)).map((l: string, i: number) => ({
            url: l,
            label: `Ссылка ${i + 1}`,
          })),
        ))
      }
      if (file) form.append('file', file)
      // НФТ-9: Idempotency-Key обязателен
      if (id) {
        await materialsApi.newVersion(id, form)
        message.success('Новая версия создана')
        navigate(`/materials/${id}`)
      } else if (gid) {
        const requestId = crypto.randomUUID()
        const m = await materialsApi.create(gid, form, requestId)
        message.success('Материал создан')
        navigate(`/materials/${m.id}`)
      }
    } catch (e: unknown) {
      message.error(errMsg(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ maxWidth: 640 }}>
      <h2>{id ? 'Новая версия материала' : 'Новый материал'}</h2>
      <Form layout="vertical" onFinish={onSubmit}>
        {!id && (
          <Form.Item name="name" label="Название" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
        )}
        <Form.Item name="description" label="Описание">
          <Input.TextArea rows={3} />
        </Form.Item>
        <Form.Item label="Файл" required={!id}>
          <Upload.Dragger
            maxCount={1}
            beforeUpload={(f) => {
              setFile(f)
              return false
            }}
          >
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">Перетащите файл или выберите</p>
          </Upload.Dragger>
        </Form.Item>
        <Form.List name="external_links">
          {(fields, { add, remove }) => (
            <>
              {fields.map((f) => (
                <Space.Compact key={f.key} style={{ width: '100%', marginBottom: 8 }}>
                  <Form.Item name={[f.name, '']} noStyle>
                    <Input placeholder="https://…" />
                  </Form.Item>
                  <Button onClick={() => remove(f.name)}>−</Button>
                </Space.Compact>
              ))}
              <Button onClick={() => add()}>+ Внешняя ссылка</Button>
            </>
          )}
        </Form.List>
        <Form.Item
          name="change_comment"
          label="Комментарий изменения"
          rules={[{ required: true, message: 'Комментарий обязателен (ВЕРС-1)' }]}
        >
          <Input.TextArea rows={2} />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={saving}>
          {id ? 'Создать версию' : 'Создать материал'}
        </Button>
      </Form>
    </div>
  )
}
