/** API-клиент: fetch с Bearer-токеном и обработкой problem+json (ui-ux §2). */

const API = '/api/v1'

let accessToken = ''

export function setToken(token: string) {
  accessToken = token
}

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  if (options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  const resp = await fetch(`${API}${path}`, { ...options, headers })
  if (resp.status === 204) return undefined as T
  const body = await resp.json().catch(() => null)
  if (!resp.ok) {
    // problem+json (api-spec §1) либо валидация FastAPI
    const detail =
      body?.detail ?? body?.title ?? body?.['message'] ?? `Ошибка ${resp.status}`
    if (resp.status === 401) {
      window.location.hash = '#/login'
    }
    throw new ApiError(resp.status, String(detail))
  }
  return body as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body === undefined ? undefined : JSON.stringify(body) }),
  post: <T>(path: string, body?: unknown, idempotencyKey?: string) => {
    const headers: Record<string, string> = {}
    if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey
    return request<T>(path, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
      headers,
    })
  },
  postForm: <T>(path: string, form: FormData, idempotencyKey?: string) => {
    const headers: Record<string, string> = {}
    if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey
    return request<T>(path, { method: 'POST', body: form, headers })
  },
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body === undefined ? undefined : JSON.stringify(body) }),
  patchForm: <T>(path: string, form: FormData) =>
    request<T>(path, { method: 'PATCH', body: form }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}

// --- Типы домена (зеркала pydantic-схем api-spec) ---

export interface Group {
  id: string
  parent_id: string | null
  name: string
  description: string | null
  nav_only: boolean
}

export interface Material {
  id: string
  group_id: string
  name: string
  status: string
  author_id: string
  current_version_id: string | null
  created_at?: string
  updated_at?: string
}

export interface Version {
  id: string
  material_id: string
  version_no: number
  description: string | null
  external_links: { url: string; label: string }[] | null
  attributes: Record<string, unknown> | null
  change_comment: string
  created_at?: string | null
  file_sha256: string
  av_status: string | null
  text_extracted: string | null
  preview_ready: boolean
}

export interface SearchHit {
  type: 'material' | 'group'
  material_id: string | null
  group_id: string | null
  name: string
  snippet: string | null
  score: number
}

export interface SearchOut {
  results: SearchHit[]
  total: number
}

export interface RoleOut {
  user_id: string
  group_id: string
  role: string
  username: string | null
  display_name: string | null
}

// --- Домен API ---

export const groupsApi = {
  roots: () => api.get<Group[]>('/groups/roots'),
  children: (id: string) => api.get<Group[]>(`/groups/${id}/children`),
  create: (parentId: string | null, name: string, description: string | null) =>
    parentId
      ? api.post<Group>(`/groups/${parentId}/children`, { name, description })
      : api.post<Group>('/groups', { name, description }),
  update: (id: string, patch: { name?: string; description?: string | null }) =>
    api.patch<Group>(`/groups/${id}`, patch),
  remove: (id: string) => api.delete<void>(`/groups/${id}`),
  move: (id: string, newParentId: string | null) =>
    api.post<Group>(`/groups/${id}/move`, { new_parent_id: newParentId }),
  roles: (id: string) => api.get<RoleOut[]>(`/groups/${id}/roles`),
  assignRole: (id: string, userId: string, role: string) =>
    api.put<RoleOut>(`/groups/${id}/roles/${userId}`, { role }),
  revokeRole: (id: string, userId: string) =>
    api.delete<void>(`/groups/${id}/roles/${userId}`),
}

export const materialsApi = {
  create: (groupId: string, form: FormData, idempotencyKey?: string) =>
    api.postForm<Material>(`/groups/${groupId}/materials`, form, idempotencyKey),
  get: (id: string) => api.get<Material>(`/materials/${id}`),
  newVersion: (id: string, form: FormData) =>
    api.patchForm<Version>(`/materials/${id}/content`, form),
  remove: (id: string) => api.delete<void>(`/materials/${id}`),
  versions: (id: string) => api.get<Version[]>(`/materials/${id}/versions`),
  move: (id: string, targetGroupId: string) =>
    api.post<Material>(`/materials/${id}/move`, { target_group_id: targetGroupId }),
  transitions: (id: string, to: string, requestId?: string) =>
    api.post<Material>(`/materials/${id}/transitions`, { to }, requestId),
}

export const searchApi = {
  query: (body: { query: string; mode: string; top_k?: number }) =>
    api.post<SearchOut>('/search', body),
}

// --- Домен API ---

export default api
