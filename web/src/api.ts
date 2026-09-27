import axios from 'axios'
import { ElMessage } from 'element-plus'

import { clearToken, getToken } from '@/utils/token'
import type {
  ContractRelatedResult,
  DocChangeLog,
  DocListQuery,
  DocListResult,
  DocRecord,
  PushRow,
  StockBalance,
  StockLedgerResult,
  StockRecalcResult,
  TakeCountInput,
} from '@/types/doc'

/**
 * 令牌导出保留（T0-5）：真源已下沉到 `@/utils/token`，此处仅转发，
 * 避免既有 `import { TOKEN_KEY } from '@/api'` 的调用点被迫同步改动。
 */
export { TOKEN_KEY } from '@/utils/token'

export const http = axios.create({ baseURL: '/api', timeout: 20000 })

// ---------- V2.0：登录态注入与统一错误处理（对应 12-erp-system-design.md §3.6） ----------
/**
 * 令牌一律经 `@/utils/token` 读取。
 *
 * 原先此处直接读 localStorage，而 `stores/auth.ts` 另存一份 `state.token`；
 * 401 时只清 localStorage、不回写 store，于是出现「store 有值 / 本地无值」的
 * 分裂态（`isLoggedIn` 仍为 true）。改由订阅机制保证两者同步。
 */
http.interceptors.request.use((config) => {
  const token = getToken()
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
    // 无 response：请求根本没到服务端（断网 / DNS / 超时 / CORS / 后端未启动）。
    // 这类错误**不得**按未登录处理，否则内网瞬时抖动会把已登录用户踢回登录页，
    // 连同当前页与未保存的录入一起丢掉。
    const isNetworkError = !error?.response
    if (status === 401) {
      // 令牌缺失/过期/账号被停用：清令牌回登录页（带 redirect 便于登录后返回）。
      // clearToken 会通知订阅者，Pinia store 随之同步清空（不再单边清理）
      clearToken()
      if (!location.pathname.startsWith('/login')) {
        const redirect = encodeURIComponent(location.pathname + location.search)
        // replace 而非 href：不在历史里留下一个注定 401 的页面
        location.replace(`/login?redirect=${redirect}`)
      }
    } else if (isNetworkError) {
      ElMessage.error('网络异常，请检查内网连接后重试')
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

// ==================== V2.0：采购线、销售线与库存单据（T-V2-24/25/29/30） ====================

/**
 * 单据接口路径规范化。
 *
 * `http` 的 `baseURL` 已是 `/api`（主数据页按 `/master/customers` 这种相对写法调用），
 * 而单据页按后端契约填写 `/api/xxx` 这种全路径。若不做处理，axios 会把两者拼成
 * `/api/api/xxx`。这里统一去掉重复前缀，两种写法都能正确落到同一个地址。
 */
export function docPath(path: string): string {
  return path.startsWith('/api/') ? path.slice(4) : path
}

/** 单据列表（7 类单据共用结构；`statuses` 为后端状态字典） */
export async function fetchDocList(path: string, params: DocListQuery = {}): Promise<DocListResult> {
  const { data } = await http.get(docPath(path), { params })
  return data as DocListResult
}

/** 单据详情（含 items） */
export async function fetchDoc(path: string, id: number): Promise<DocRecord> {
  const { data } = await http.get(`${docPath(path)}/${id}`)
  return data as DocRecord
}

export async function createDoc(path: string, payload: Dict): Promise<DocRecord> {
  const { data } = await http.post(docPath(path), payload)
  return data as DocRecord
}

export async function updateDoc(path: string, id: number, payload: Dict): Promise<DocRecord> {
  const { data } = await http.put(`${docPath(path)}/${id}`, payload)
  return data as DocRecord
}

/** 通用状态动作：submit / approve / complete / reject / void / unapprove */
export async function docAction(
  path: string,
  id: number,
  action: 'submit' | 'approve' | 'complete' | 'reject' | 'void' | 'unapprove',
  payload: Dict = {},
): Promise<DocRecord> {
  const { data } = await http.post(`${docPath(path)}/${id}/${action}`, payload)
  return data as DocRecord
}

/** 下推：生成下游单据（申请→订单 / 订单→出入库单） */
export async function pushDoc(path: string, id: number, payload: Dict): Promise<DocRecord> {
  const { data } = await http.post(`${docPath(path)}/${id}/push`, payload)
  return data as DocRecord
}

/** 单据变更历史 */
export async function fetchDocChangelogs(path: string, id: number): Promise<DocChangeLog[]> {
  const { data } = await http.get(`${docPath(path)}/${id}/changelogs`)
  return data as DocChangeLog[]
}

/** 盘点单：按商品类型 / 指定物料生成行项（账面数量取当前结存） */
export async function generateTakeItems(path: string, id: number, payload: Dict = {}): Promise<DocRecord> {
  const { data } = await http.post(`${docPath(path)}/${id}/generate`, payload)
  return data as DocRecord
}

/** 盘点单：录入实盘数量（后端据此计算 diff_qty） */
export async function saveTakeCounts(
  path: string, id: number, counts: TakeCountInput[],
): Promise<DocRecord> {
  const { data } = await http.put(`${docPath(path)}/${id}/count`, { counts })
  return data as DocRecord
}

/** 可关联的采购合同下拉（仅采购方向合同） */
export async function fetchPurchaseContractOptions(keyword = ''): Promise<Dict[]> {
  const { data } = await http.get('/purchase/contract-options', {
    params: keyword ? { keyword } : {},
  })
  return data as Dict[]
}

/** 可关联的销售合同下拉（仅销售方向合同） */
export async function fetchSalesContractOptions(keyword = ''): Promise<Dict[]> {
  const { data } = await http.get('/sales/contract-options', {
    params: keyword ? { keyword } : {},
  })
  return data as Dict[]
}

// ---------------- 导出与打印（T-V2-35/37） ----------------

/** 从 Content-Disposition 取文件名（后端用 RFC 5987 的 `filename*=UTF-8''…`） */
function filenameFromDisposition(disposition: unknown, fallback: string): string {
  const text = typeof disposition === 'string' ? disposition : ''
  const star = /filename\*=UTF-8''([^;]+)/i.exec(text)
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1])
    } catch {
      return fallback
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(text)
  return plain?.[1] ? plain[1] : fallback
}

/** 需带令牌的下载：blob 取回后触发浏览器保存（不能直接用 URL，令牌在请求头） */
export async function downloadBlobFile(
  path: string, params: Dict = {}, fallbackName = '导出.xlsx',
): Promise<void> {
  const resp = await http.get(docPath(path), { params, responseType: 'blob', timeout: 120000 })
  const url = URL.createObjectURL(resp.data as Blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filenameFromDisposition(
    (resp.headers as Dict | undefined)?.['content-disposition'], fallbackName)
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

/** 单据导出 Excel（7 类单据 + 库存结存/流水，筛选参数与列表一致） */
export async function exportDoc(
  path: string, params: DocListQuery = {}, fallbackName = '单据导出.xlsx',
): Promise<void> {
  await downloadBlobFile(path, params as Dict, fallbackName)
}

/**
 * 打印单据：取回可打印 HTML（令牌在请求头，不能拼进 URL），在新窗口打开后由用户点「打印」。
 *
 * 注意：窗口必须**同步**打开，否则会被浏览器判定为弹窗而拦截。
 */
export async function openDocPrint(path: string): Promise<void> {
  const win = window.open('', '_blank')
  try {
    const resp = await http.get(docPath(path), { responseType: 'blob' })
    const url = URL.createObjectURL(resp.data as Blob)
    if (win) {
      win.location.href = url
    } else {
      // 弹窗被拦截：退化为当前标签页打开 Blob（用户仍可用浏览器返回）
      window.open(url, '_blank')
      ElMessage.warning('浏览器拦截了新窗口，已尝试直接打开打印页')
    }
    // Blob 需要保留给新窗口渲染，延迟释放
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  } catch (error) {
    win?.close()
    throw error
  }
}

/** 合同关联单据（后端未就绪时 404，调用方需容错） */
export async function fetchContractRelatedDocs(id: number): Promise<ContractRelatedResult> {
  const { data } = await http.get(`/contracts/${id}/related-docs`)
  return data as ContractRelatedResult
}

// ==================== V2.2：单据打印模板（BR-V2.2-02） ====================

/** 打印模板列表（八类单据）+ 编辑界面元数据（区块/字段/列目录） */
export async function fetchPrintTemplates(): Promise<Dict> {
  const { data } = await http.get('/system/print-templates')
  return data
}

/** 单个单据类型的模板（含出厂默认值对照，用于「恢复默认」与差异提示） */
export async function fetchPrintTemplate(kind: string): Promise<Dict> {
  const { data } = await http.get(`/system/print-templates/${kind}`)
  return data
}

/** 保存模板（整表替换语义；后端会归一化，未知字段会被丢弃） */
export async function savePrintTemplate(kind: string, config: Dict): Promise<Dict> {
  const { data } = await http.put(`/system/print-templates/${kind}`, { config })
  return data
}

/** 恢复出厂模板 */
export async function resetPrintTemplate(kind: string): Promise<Dict> {
  const { data } = await http.post(`/system/print-templates/${kind}/reset`)
  return data
}

/**
 * 预览：用**提交的（可能尚未保存的）配置**渲染样例单据，返回完整 HTML。
 *
 * 走 POST + `responseType: 'text'`：配置是结构化 JSON（塞进 URL 会超长），
 * 拿到 HTML 后写进 iframe 的 `srcdoc`，因此不需要额外的带令牌 URL。
 */
export async function previewPrintTemplate(kind: string, config: Dict): Promise<string> {
  const { data } = await http.post(`/system/print-templates/${kind}/preview`, { config },
                                   { responseType: 'text' })
  return data as string
}

/** 库存结存列表 */
export async function fetchBalances(params: Dict = {}): Promise<{
  items: StockBalance[]
  total: number
  page: number
  page_size: number
}> {
  const { data } = await http.get('/stock/balances', { params })
  return data
}

/** 库存流水（按物料 + 仓库下钻） */
export async function fetchLedger(params: Dict = {}): Promise<StockLedgerResult> {
  const { data } = await http.get('/stock/ledger', { params })
  return data as StockLedgerResult
}

/** 结存重算校验（fix=true 时按流水修复） */
export async function recalcStock(fix = false): Promise<StockRecalcResult> {
  const { data } = await http.post('/stock/recalc', {}, { params: { fix } })
  return data as StockRecalcResult
}

export type {
  DocItem, DocRecord, DocListQuery, DocListResult, PushRow, TakeCountInput,
} from '@/types/doc'
