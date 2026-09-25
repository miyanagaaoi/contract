import axios from 'axios'
import { ElMessage } from 'element-plus'

export const TOKEN_KEY = 'ctms_token'

export const http = axios.create({ baseURL: '/api', timeout: 20000 })

// ---------- V2.0：登录态注入与统一错误处理（对应 12-erp-system-design.md §3.6） ----------
http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    // AxiosHeaders 在 1.x 下支持属性赋值；用 any 规避类型细节
    ;(config.headers as Record<string, string>).Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const status = error?.response?.status
    const detail = error?.response?.data?.detail
    if (status === 401) {
      // 令牌缺失/过期/账号被停用：清本地令牌回登录页（带 redirect 便于登录后返回）
      localStorage.removeItem(TOKEN_KEY)
      if (!location.pathname.startsWith('/login')) {
        const redirect = encodeURIComponent(location.pathname + location.search)
        location.href = `/login?redirect=${redirect}`
      }
    } else if (status === 403) {
      ElMessage.error(typeof detail === 'string' ? detail : '无权限执行该操作')
    } else if (typeof detail === 'string') {
      ElMessage.error(detail)
    }
    return Promise.reject(error)
  },
)

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

// ---------- 附件（T7，AC-09） ----------
export async function fetchAttachments(contractId: number): Promise<Dict[]> {
  const { data } = await http.get(`/contracts/${contractId}/attachments`)
  return data
}

export async function uploadAttachment(contractId: number, file: File): Promise<Dict> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post(`/contracts/${contractId}/attachments`, form)
  return data
}

export async function deleteAttachment(contractId: number, attachmentId: number, reason?: string): Promise<Dict> {
  const { data } = await http.delete(`/contracts/${contractId}/attachments/${attachmentId}`, {
    params: reason ? { reason } : {},
  })
  return data
}

export function attachmentUrl(attachmentId: number, inline = false): string {
  return `/api/attachments/${attachmentId}/download${inline ? '?inline=1' : ''}`
}

const PREVIEWABLE = ['.pdf', '.png', '.jpg', '.jpeg', '.gif']

export function canPreview(fileName: string): boolean {
  const dot = fileName.lastIndexOf('.')
  if (dot < 0) return false
  return PREVIEWABLE.includes(fileName.slice(dot).toLowerCase())
}

// ---------- 看板（T9，AC-08） ----------
export async function fetchDashboard(): Promise<Dict> {
  const { data } = await http.get('/dashboard')
  return data
}

// ---------- 系统设置/字典（MVP2：行项类型；MVP3：合同类型/主体） ----------
export async function saveItemTypes(values: string[]): Promise<Dict> {
  const { data } = await http.put('/settings/item-types', { values })
  return data
}

export async function saveContractTypes(contractTypes: Dict[]): Promise<Dict> {
  const { data } = await http.put('/settings/contract-types', { contract_types: contractTypes })
  return data
}

export async function saveSubjects(subjects: Dict[]): Promise<Dict> {
  const { data } = await http.put('/settings/subjects', { subjects })
  return data
}

// ---------- 自动编号预览（MVP3） ----------
export async function previewNumber(typeValue: string, subject: string, signDate?: string): Promise<Dict> {
  const { data } = await http.get('/contracts/next-no', {
    params: { type: typeValue, subject, sign_date: signDate || undefined },
  })
  return data
}

// ---------- 批量导入（MVP2 需求②：仅新建） ----------
export function importTemplateUrl(): string {
  return '/api/import/template.xlsx'
}

export async function importContracts(file: File): Promise<Dict> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post('/import/contracts', form, { timeout: 120000 })
  return data
}

// ==================== V2.0：主数据（T-V2-07~11） ====================

export async function fetchMasterMeta(): Promise<Dict> {
  const { data } = await http.get('/master/meta')
  return data
}

/** 通用列表：path 形如 '/master/customers'；返回 {items,total,page,page_size} 或 {items,total} */
export async function fetchMasterList(path: string, params: Dict = {}): Promise<Dict> {
  const { data } = await http.get(path, { params })
  return data
}

export async function fetchMasterItem(path: string, id: number): Promise<Dict> {
  const { data } = await http.get(`${path}/${id}`)
  return data
}

export async function createMasterItem(path: string, payload: Dict): Promise<Dict> {
  const { data } = await http.post(path, payload)
  return data
}

export async function updateMasterItem(path: string, id: number, payload: Dict): Promise<Dict> {
  const { data } = await http.put(`${path}/${id}`, payload)
  return data
}

export async function setMasterStatus(path: string, id: number, enabled: boolean): Promise<Dict> {
  const { data } = await http.put(`${path}/${id}/status`, { enabled })
  return data
}

export async function deleteMasterItem(path: string, id: number): Promise<Dict> {
  const { data } = await http.delete(`${path}/${id}`)
  return data
}

/** 轻量下拉（客户/供应商/物料/商品类型/单位/仓库） */
export async function fetchMasterOptions(kind: string, params: Dict = {}): Promise<Dict[]> {
  const { data } = await http.get(`/master/options/${kind}`, { params })
  return data
}

// ==================== V2.0：系统管理（T-V2-12） ====================

export async function fetchSysParams(): Promise<Dict> {
  const { data } = await http.get('/system/params')
  return data
}

export async function saveSysParams(params: Dict): Promise<Dict> {
  const { data } = await http.put('/system/params', { params })
  return data
}

export async function fetchNumberRules(): Promise<Dict> {
  const { data } = await http.get('/system/number-rules')
  return data
}

export async function saveNumberRules(rules: Dict): Promise<Dict> {
  const { data } = await http.put('/system/number-rules', { rules })
  return data
}

export async function fetchOperationLogs(params: Dict = {}): Promise<Dict> {
  const { data } = await http.get('/system/logs', { params })
  return data
}

export async function fetchChangeLogs(params: Dict = {}): Promise<Dict> {
  const { data } = await http.get('/system/changelogs', { params })
  return data
}

export async function fetchBackups(): Promise<Dict[]> {
  const { data } = await http.get('/system/backup')
  return data.items
}

export async function createBackup(): Promise<Dict> {
  const { data } = await http.post('/system/backup')
  return data
}

export async function deleteBackup(name: string): Promise<Dict> {
  const { data } = await http.delete(`/system/backup/${encodeURIComponent(name)}`)
  return data
}

export async function fetchAbout(): Promise<Dict> {
  const { data } = await http.get('/system/about')
  return data
}

/** 备份下载走浏览器直接下载（需带 token → 用 blob 请求） */
export async function downloadBackup(name: string): Promise<void> {
  const resp = await http.get(`/system/backup/${encodeURIComponent(name)}`, {
    responseType: 'blob',
  })
  const url = URL.createObjectURL(resp.data as Blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}

// ==================== V2.0：历史档案迁移（T-V2-14） ====================

export async function migrateParties(): Promise<Dict> {
  const { data } = await http.post('/contracts/migrate-parties')
  return data
}

export async function fetchPartyDrafts(status = 'pending'): Promise<Dict> {
  const { data } = await http.get('/contracts/party-drafts', { params: { status } })
  return data
}

export async function claimPartyDraft(id: number, payload: Dict = {}): Promise<Dict> {
  const { data } = await http.post(`/contracts/party-drafts/${id}/claim`, payload)
  return data
}

export async function ignorePartyDraft(id: number, reason?: string): Promise<Dict> {
  const { data } = await http.post(`/contracts/party-drafts/${id}/ignore`, { reason })
  return data
}
