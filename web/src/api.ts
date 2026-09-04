import axios from 'axios'

export const http = axios.create({ baseURL: '/api', timeout: 20000 })

// 宽松字典类型：原型阶段避免过度建模，字段与后端 _fmt 对齐
export interface Dict {
  [key: string]: any // eslint-disable-line @typescript-eslint/no-explicit-any
}

export interface PageResult {
  items: Dict[]
  total: number
  page: number
  page_size: number
}

export async function getMeta(): Promise<Dict> {
  const { data } = await http.get('/meta')
  return data
}

export async function fetchContracts(params: Dict): Promise<PageResult> {
  const { data } = await http.get('/contracts', { params })
  return data
}

export async function fetchContract(id: number): Promise<Dict> {
  const { data } = await http.get(`/contracts/${id}`)
  return data
}

export async function fetchLogs(id: number): Promise<Dict[]> {
  const { data } = await http.get(`/contracts/${id}/logs`)
  return data
}

export async function createContract(payload: Dict): Promise<Dict> {
  const { data } = await http.post('/contracts', payload)
  return data
}

export async function updateContract(id: number, payload: Dict): Promise<Dict> {
  const { data } = await http.put(`/contracts/${id}`, payload)
  return data
}

export async function softDeleteContract(id: number, reason: string): Promise<Dict> {
  const { data } = await http.delete(`/contracts/${id}`, { params: { reason } })
  return data
}

export async function restoreContract(id: number): Promise<Dict> {
  const { data } = await http.put(`/contracts/${id}/restore`)
  return data
}

// ---------- 标签（T4，AC-05/13） ----------
export async function fetchTags(): Promise<Dict[]> {
  const { data } = await http.get('/tags')
  return data
}

export async function createTag(name: string): Promise<Dict> {
  const { data } = await http.post('/tags', { name })
  return data
}

export async function renameTag(id: number, name: string): Promise<Dict> {
  const { data } = await http.put(`/tags/${id}`, { name })
  return data
}

export async function deleteTag(id: number): Promise<Dict> {
  const { data } = await http.delete(`/tags/${id}`)
  return data
}
