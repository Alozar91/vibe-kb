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
  isLeaf?: boolean
}

/** Состояние дерева: корни + загруженные дети по ключу родителя (ленивая загрузка ГРП-2). */
interface TreeState {
  roots: Group[]
  childrenOf: Record<string, Group[]>
  loaded: Record<string, boolean> // дети запрашивались (пустой список = узел лист)
}

export default function MainPage() {
  const navigate = useNavigate()
  const [tree, setTree] = useState<TreeState>({ roots: [], childrenOf: {}, loaded: {} })
  const [expandedKeys, setExpandedKeys] = useState<React.Key[]>([])
  const [selected, setSelected] = useState<Group | null>(null)
  const [materials, setMaterials] = useState<Material[]>([])
  const [loading, setLoading] = useState(false)
  const [newGroupName, setNewGroupName] = useState('')

  const loadRoots = () =>
    groupsApi.roots()
      .then((roots) => setTree((t) => ({ ...t, roots })))
      .catch((e) => message.error(errMsg(e)))

  const loadChildren = async (parentId: string): Promise<Group[]> => {
    const children = await groupsApi.children(parentId)
    setTree((t) => ({
      ...t,
      childrenOf: { ...t.childrenOf, [parentId]: children },
      loaded: { ...t.loaded, [parentId]: true },
    }))
    return children
  }

  useEffect(() => {
    void loadRoots()
  }, [])

  /** Найти группу на любом уровне загруженного дерева. */
  const findGroup = (list: Group[], id: string): Group | null => {
    for (const g of list) {
      if (g.id === id) return g
      const inChild = findGroup(tree.childrenOf[g.id] ?? [], id)
      if (inChild) return inChild
    }
    return null
  }

  const buildTreeData = (list: Group[]): TreeNode[] =>
    list.map((g) => {
      const kids = tree.childrenOf[g.id] ?? []
      const children = kids.length > 0 ? buildTreeData(kids) : undefined
      return {
        title: g.name,
        key: g.id,
        // дети не загружены → узел раскрываемый (loadData); загружены и пусты → лист
        isLeaf: tree.loaded[g.id] === true && kids.length === 0,
        children,
      }
    })

  const onSelectGroup = async (key: string) => {
    const g = findGroup(tree.roots, key)
    if (g) {
      if (g.nav_only) return // ПРВ-2: nav-only — только транзит
      setSelected(g)
      setLoading(true)
      try {
        // материалы группы (api-spec §2: GET /groups/{id}/materials)
        setMaterials(await materialsApi.listForGroup(key))
      } catch {
        setMaterials([]) // нет прав/пусто — молча
      } finally {
        setLoading(false)
      }
    }
  }

  const createGroup = async () => {
    if (!newGroupName.trim()) return
    try {
      const parentId = selected ? selected.id : null
      await groupsApi.create(parentId, newGroupName.trim(), null)
      setNewGroupName('')
      message.success('Группа создана')
      // обновляем уровень, куда добавили, и раскрываем родителя
      if (parentId) {
        await loadChildren(parentId)
        setExpandedKeys((keys) => (keys.includes(parentId) ? keys : [...keys, parentId]))
      } else {
        await loadRoots()
      }
    } catch (e: unknown) {
      message.error(errMsg(e))
    }
  }

  const deleteGroup = async (id: string) => {
    const parentId = selected?.parent_id ?? null
    try {
      await groupsApi.remove(id)
      message.success('Группа удалена')
      setSelected(null)
      // убираем удалённую из кэша детей
      setTree((t) => {
        const childrenOf = { ...t.childrenOf }
        delete childrenOf[id]
        return { ...t, childrenOf }
      })
      if (parentId) await loadChildren(parentId)
      else await loadRoots()
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
            treeData={buildTreeData(tree.roots)}
            expandedKeys={expandedKeys}
            onExpand={(keys) => setExpandedKeys(keys)}
            selectedKeys={selected ? [selected.id] : []}
            loadData={async (node) => {
              await loadChildren(String(node.key))
            }}
            onSelect={(keys) => keys[0] && void onSelectGroup(String(keys[0]))}
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
