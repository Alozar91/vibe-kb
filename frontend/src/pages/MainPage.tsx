import { useEffect, useState } from 'react'
import { Button, Layout, Table, Tree, Breadcrumb, Input, Space, message } from 'antd'
import { Outlet, useNavigate } from 'react-router-dom'
import { groupsApi, materialsApi, type Group, type Material } from '../shared/api/client'
import { logout } from '../shared/api/auth'


function errMsg(e: unknown): string {
  if (e && typeof e === "object" && "detail" in e && typeof (e as { detail?: unknown }).detail === "string") {
    return (e as { detail: string }).detail
  }
  if (e instanceof Error) return e.message
  return "Ошибка"
}


const { Header, Sider, Content } = Layout

interface TreeNode {
  title: React.ReactNode
  key: string
  children?: TreeNode[]
  navOnly?: boolean
}

export default function MainPage() {
  const navigate = useNavigate()
  const [groups, setGroups] = useState<Group[]>([])
  const [selected, setSelected] = useState<Group | null>(null)
  const [materials, setMaterials] = useState<Material[]>([])
  const [loading, setLoading] = useState(false)
  const [newGroupName, setNewGroupName] = useState('')

  const loadRoots = () => groupsApi.roots().then(setGroups).catch((e) => message.error(errMsg(e)))

  useEffect(() => {
    loadRoots()
  }, [])

  const buildTreeData = (): TreeNode[] =>
    groups.map((g) => ({ title: g.name, key: g.id, navOnly: g.nav_only, children: [] }))

  const onSelectGroup = async (key: string) => {
    const g = groups.find((x) => x.id === key)
    if (g) {
      if (g.nav_only) return // ПРВ-2: nav-only — только транзит
      setSelected(g)
      setLoading(true)
      try {
        // материалы группы (api-spec §2: GET /groups/{id}/materials)
        setMaterials(await materialsApi.listForGroup(key))
      } catch {
        setMaterials([]) // нет прав/пусто — молча, как раньше
      } finally {
        setLoading(false)
      }
    }
  }

  const createGroup = async () => {
    if (!newGroupName.trim()) return
    try {
      if (selected) await groupsApi.create(selected.id, newGroupName.trim(), null)
      else await groupsApi.create(null, newGroupName.trim(), null)
      setNewGroupName('')
      message.success('Группа создана')
      await loadRoots()
    } catch (e: unknown) {
      message.error(errMsg(e))
    }
  }

  const deleteGroup = async (id: string) => {
    try {
      await groupsApi.remove(id)
      message.success('Группа удалена')
      setSelected(null)
      await loadRoots()
    } catch (e: unknown) {
      message.error(errMsg(e))
    }
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ background: '#fff', borderBottom: '1px solid #eee', display: 'flex', alignItems: 'center', gap: 16 }}>
        <h2 style={{ margin: 0 }}>База знаний</h2>
        <Input.Search
          placeholder="Поиск по базе…"
          style={{ width: 400 }}
          onSearch={(q) => navigate(`/search?q=${encodeURIComponent(q)}`)}
        />
        <Button type="primary" onClick={() => navigate('/search')}>Поиск</Button>
        <Button onClick={logout} style={{ marginLeft: 'auto' }}>Выйти</Button>
      </Header>
      <Layout>
        <Sider width={280} style={{ background: '#fff', borderRight: '1px solid #eee', padding: 12 }}>
          <Space.Compact style={{ width: '100%', marginBottom: 8 }}>
            <Input
              value={newGroupName}
              onChange={(e) => setNewGroupName(e.target.value)}
              placeholder={selected ? 'Новая подгруппа' : 'Новая корневая группа'}
            />
            <Button onClick={createGroup}>+</Button>
          </Space.Compact>
          <Tree
            treeData={buildTreeData()}
            loadData={async (node) => {
              const children = await groupsApi.children(String(node.key))
              node.children = children.map((c) => ({ title: c.name, key: c.id, navOnly: c.nav_only, children: [] }))
              setGroups((prev) => prev) // перерисовка
            }}
            onSelect={(keys) => keys[0] && onSelectGroup(String(keys[0]))}
          />
        </Sider>
        <Content style={{ padding: 24 }}>
          <Breadcrumb items={selected ? [{ title: 'Группы' }, { title: selected.name }] : [{ title: 'Группы' }]} />
          {selected && (
            <>
              <div style={{ margin: '16px 0', display: 'flex', gap: 8 }}>
                <Button danger onClick={() => deleteGroup(selected.id)}>
                  Удалить группу
                </Button>
                <Button
                  type="primary"
                  onClick={() => navigate(`/groups/${selected.id}/new-material`)}
                >
                  Создать материал
                </Button>
              </div>
              <Table<Material>
                rowKey="id"
                loading={loading}
                dataSource={materials}
                columns={[
                  { title: 'Название', dataIndex: 'name', render: (n, r) => <a onClick={() => navigate(`/materials/${r.id}`)}>{n}</a> },
                  { title: 'Статус', dataIndex: 'status' },
                  { title: 'Обновлён', dataIndex: 'updated_at' },
                ]}
                onRow={(r) => ({ onClick: () => navigate(`/materials/${r.id}`) })}
              />
            </>
          )}
          {!selected && <p>Выберите группу в дереве слева (ПРВ-5: пустое дерево — обратитесь к владельцу раздела).</p>}
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
