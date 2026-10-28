<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import RelatedDocs from '@/components/doc/RelatedDocs.vue'
import {
  canPreview,
  createContract,
  createTag,
  deleteAttachment,
  deleteTag,
  downloadAttachment,
  downloadBlobFile,
  fetchAttachments,
  fetchContract,
  fetchContracts,
  fetchLogs,
  fetchMasterOptions,
  fetchTags,
  getMeta,
  importContracts,
  previewAttachment,
  previewNumber,
  renameTag,
  restoreContract,
  saveItemTypes,
  softDeleteContract,
  updateContract,
  uploadAttachment,
  type Dict,
} from '@/api'
import ProductTreeSelect from '@/components/doc/ProductTreeSelect.vue'
import { useAuthStore } from '@/stores/auth'
import { fmtDate, fmtDateTime, fmtMoney } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

// ---------- 状态 ----------
const rows = ref<Dict[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)

const meta = ref<Dict>({ contract_types: [], statuses: [], arrival_statuses: [], subjects: [] })
const frameworks = ref<Dict[]>([])
const tagOptions = ref<Dict[]>([])

const query = reactive<Dict>({
  keyword: '',
  type: '',
  status: '',
  owner: '',
  tags: [] as string[],
  date_range: [] as string[],
  include_deleted: false,
})

// ---------- 框架树视图（MVP2 需求⑤：树=展示层，筛选/导出仍按平铺语义） ----------
const viewMode = ref<'flat' | 'tree'>('flat')
const collapsedIds = ref<number[]>([])
const isTree = computed(() => viewMode.value === 'tree')

const viewRows = computed<Dict[]>(() => {
  const all = rows.value
  if (viewMode.value !== 'tree') return all
  const out: Dict[] = []
  let skip = false
  for (const r of all) {
    if (r.tree === 'f') {
      skip = collapsedIds.value.includes(r.id)
      out.push(r)
    } else if (r.tree === 'c') {
      if (!skip) out.push(r)
    } else {
      out.push(r)
    }
  }
  return out
})

function toggleFw(id: number) {
  const i = collapsedIds.value.indexOf(id)
  if (i >= 0) collapsedIds.value.splice(i, 1)
  else collapsedIds.value.push(id)
}

function switchView(mode: 'flat' | 'tree') {
  viewMode.value = mode
  page.value = 1
  load()
}

function onViewModeChange(v: unknown) {
  switchView(v === 'tree' ? 'tree' : 'flat')
}

function rowClass({ row }: { row: Dict }): string {
  if (row.tree === 'c') return 'tree-child-row'
  if (row.tree === 'f') return 'tree-fw-row'
  return ''
}

// ---------- 列表 ----------
/**
 * 筛选参数（T2-3）。
 *
 * 抽成独立函数让「列表请求」与「URL 同步」共用同一口径——否则两处各写一遍，
 * 迟早出现「URL 里有、请求里没有」的漂移。
 */
function filterParams(): Dict {
  const params: Dict = {}
  if (query.keyword) params.keyword = query.keyword
  if (query.type) params.type = query.type
  if (query.status) params.status = query.status
  if (query.owner) params.owner = query.owner
  if (query.tags.length) params.tags = query.tags.join(',')
  if (query.date_range.length === 2) {
    params.sign_from = query.date_range[0]
    params.sign_to = query.date_range[1]
  }
  if (query.include_deleted) params.include_deleted = true
  if (viewMode.value === 'tree') params.tree = true
  return params
}

/**
 * 把当前筛选与分页写入 URL query（T2-3）。
 *
 * 此前全项目**没有任何页面**把筛选写进 URL：链接无法分享、刷新丢筛选、
 * 浏览器回退直接离开页面。这里只写入非默认值，避免 URL 噪音。
 */
function syncQueryToUrl(): void {
  const q: Record<string, string> = {}
  for (const [key, value] of Object.entries(filterParams())) {
    q[key] = String(value)
  }
  if (page.value > 1) q.page = String(page.value)
  if (pageSize.value !== 20) q.page_size = String(pageSize.value)
  router.replace({ query: q })
}

/** 首挂载时从 URL 回填筛选（深链 / 分享链接 / 刷新保持） */
function applyQueryFromUrl(): void {
  const q = route.query
  const str = (key: string): string => (typeof q[key] === 'string' ? (q[key] as string) : '')
  query.keyword = str('keyword')
  query.type = str('type')
  query.status = str('status')
  query.owner = str('owner')
  const tags = str('tags')
  query.tags = tags ? tags.split(',').filter(Boolean) : []
  const from = str('sign_from')
  const to = str('sign_to')
  query.date_range = from && to ? [from, to] : []
  query.include_deleted = str('include_deleted') === 'true'
  viewMode.value = str('tree') === 'true' ? 'tree' : 'flat'
  const p = Number(str('page'))
  page.value = Number.isFinite(p) && p > 0 ? p : 1
}

async function load() {
  loading.value = true
  try {
    const params: Dict = { ...filterParams(), page: page.value, page_size: pageSize.value }
    const res = await fetchContracts(params)
    rows.value = res.items
    total.value = res.total
    syncQueryToUrl()
  } finally {
    loading.value = false
  }
}

/**
 * 重置筛选（T2-6）。
 *
 * 原实现是模板里的一句 `Object.assign(query, {...})`，漏了两个字段：
 * - `include_deleted`：勾选「显示已停用」后点重置，仍停留在停用视图；
 * - `page`：重置后可能停在原来的第 N 页，看到空白列表。
 */
function resetQuery() {
  Object.assign(query, {
    keyword: '',
    type: '',
    status: '',
    owner: '',
    tags: [],
    date_range: [],
    include_deleted: false,
  })
  page.value = 1
  load()
}

async function loadFrameworks() {
  const res = await fetchContracts({ page: 1, page_size: 200, is_framework: true })
  frameworks.value = res.items
}

async function loadTags() {
  tagOptions.value = await fetchTags()
}

function exportExcel() {
  const p = new URLSearchParams()
  if (query.keyword) p.set('keyword', query.keyword)
  if (query.type) p.set('type', query.type)
  if (query.status) p.set('status', query.status)
  if (query.owner) p.set('owner', query.owner)
  if (query.tags.length) p.set('tags', query.tags.join(','))
  if (query.date_range.length === 2) {
    p.set('sign_from', query.date_range[0])
    p.set('sign_to', query.date_range[1])
  }
  if (query.include_deleted) p.set('include_deleted', 'true')
  return p
}

// ---------- 导出配置（MVP2 需求③：重要列默认勾 + 记住选择） ----------
const exportDlgVisible = ref(false)
const exportCols = ref<string[]>([])
const exportRemember = ref(true)
const MEM_KEY = 'ctms_export_cols'

const impExportCols = computed(() => (meta.value.export_columns ?? []).filter((c: Dict) => c.important))
const optExportCols = computed(() => (meta.value.export_columns ?? []).filter((c: Dict) => !c.important))

function openExportDialog() {
  const defaults = meta.value.export_default_cols ?? []
  let list: string[] | null = null
  if (exportRemember.value) {
    try {
      const saved = localStorage.getItem(MEM_KEY)
      if (saved) {
        const arr = JSON.parse(saved)
        if (Array.isArray(arr)) list = arr.filter((k: string) => defaults.includes(k))
      }
    } catch { /* ignore */ }
  }
  exportCols.value = list && list.length ? list : [...defaults]
  exportDlgVisible.value = true
}

function rememberExportCols() {
  try {
    localStorage.setItem(MEM_KEY, JSON.stringify(exportCols.value))
  } catch { /* ignore */ }
}

function setAllExportCols() {
  exportCols.value = (meta.value.export_columns ?? []).map((c: Dict) => c.key)
  if (exportRemember.value) rememberExportCols()
}

function clearExportCols() {
  exportCols.value = []
  if (exportRemember.value) rememberExportCols()
}

function resetExportCols() {
  exportCols.value = [...(meta.value.export_default_cols ?? [])]
  if (exportRemember.value) rememberExportCols()
}

async function doExport() {
  if (!exportCols.value.length) {
    ElMessage.warning('请至少选择一列')
    return
  }
  if (exportRemember.value) rememberExportCols()
  // 令牌在请求头 → 必须走 blob 下载；`window.open('/api/export/…')` 不带 Authorization 会 401
  const params = Object.fromEntries(exportExcel().entries())
  params.cols = exportCols.value.join(',')
  try {
    await downloadBlobFile('/export/contracts.xlsx', params, '合同台账.xlsx')
  } catch (e) {
    ElMessage.error(apiError(e))
    return
  }
  exportDlgVisible.value = false
}

// ---------- 新增/编辑 ----------
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const form = reactive<Dict>({
  contract_no: '', name: '', type: '采购', party_a: '', party_b: '',
  customer_id: null, supplier_id: null,
  sign_date: '', amount: 0, paid_amount: 0, received_amount: 0, status: '内部审批中',
  owner_name: '', remark: '', is_framework: false, parent_id: null, tags: [],
  items: [] as Dict[], subject_code: '',
  has_warranty: false, warranty_amount: null, warranty_rate: null,
  warranty_start: '', warranty_months: null,
})

// ---------- V2.0：往来单位档案化（T-V2-13 / AC-V2-33） ----------
const customerOptions = ref<Dict[]>([])
const supplierOptions = ref<Dict[]>([])

/** 当前表单类型的标准代码（PUR/SAL/...） */
const typeCode = computed(() => {
  const value = String(form.type || '')
  const defs = (meta.value.contract_type_defs || []) as Dict[]
  const hit = defs.find((d) => d.label === value || d.code === value)
  return String(hit?.code || '')
})
const isPurchaseType = computed(() => typeCode.value === 'PUR')
const isSalesType = computed(() => typeCode.value === 'SAL')

/**
 * 合同方向的**行级**判定（列表/详情用）：先按类型定义表把标签/代码映射回标准码
 * （`销售/收入`→SAL），映射不到时（历史纯文本"销售"、字典项被停用）用关键词兜底。
 *
 * 口径（V2.5+）：销售/收入类合同的金额来自**收款单**（`received_amount`），
 * 其余来自**付款单**（`paid_amount`）—— 同一列「已付（比例）」按类型二选一显示，
 * 分母都是合同金额，故两个比例字段也二选一。
 */
function isSalesRow(type: unknown): boolean {
  const value = String(type ?? '')
  const defs = (meta.value.contract_type_defs || []) as Dict[]
  const code = String(defs.find((d) => d.label === value || d.code === value)?.code || '')
  if (code) return code === 'SAL'
  return value.includes('销售') || value.includes('收入')
}

function rowAmount(row: Dict) {
  return isSalesRow(row.type) ? row.received_amount : row.paid_amount
}

function rowRatio(row: Dict) {
  return isSalesRow(row.type) ? row.receipt_ratio : row.payment_ratio
}

async function loadPartyOptions() {
  try {
    const [customers, suppliers] = await Promise.all([
      fetchMasterOptions('customer'),
      fetchMasterOptions('supplier'),
    ])
    customerOptions.value = customers
    supplierOptions.value = suppliers
  } catch {
    // 档案下拉不可用时仍可纯文本录入（AC-V2-34）
  }
}

// ---------- 经办人：系统用户下拉（与单据页 `DocFormPage` 同源） ----------
/**
 * `Contract` 只有文本字段 `owner_name`（无 `handler_user_id`），因此这里**绑姓名**：
 * 下拉 `value` 就是用户姓名，选中即写入既有的 `owner_name`。
 * 好处是历史数据（纯文本/已停用账号）原样保留、后端与"提取合同明细"等调用方零改动；
 * 代价是同名账号无法区分——对内网 3~4 人规模可接受。
 */
const ownerOptions = ref<Dict[]>([])

async function loadOwnerOptions() {
  try {
    ownerOptions.value = await fetchMasterOptions('user')
  } catch {
    // 取不到账号列表时不阻塞表单：`ownerChoices` 会把已有 owner_name 兜底显示出来，
    // 用户仍可保存原文（历史数据不因接口异常而丢）
    ownerOptions.value = []
  }
}

/**
 * 下拉候选：历史 `owner_name` 不在启用账号列表里时（账号被停用、或早期纯文本录入），
 * 补一条同名选项，否则 `el-select` 会显示空白、看起来像"经办人丢了"。
 * 兜底项没有登录名，label 只显示姓名（与改动前的纯文本输入观感一致）。
 */
const ownerChoices = computed<Dict[]>(() => {
  const name = String(form.owner_name || '')
  if (!name || ownerOptions.value.some((u) => u.name === name)) return ownerOptions.value
  return [...ownerOptions.value, { id: `raw:${name}`, name, username: '' }]
})

/** 选择档案后写入名称快照（后端同样会回填，前端即时可见） */
function onCustomerChange(id: number | null) {
  const hit = customerOptions.value.find((c) => c.id === id)
  if (hit) form.party_a = hit.name
}

function onSupplierChange(id: number | null) {
  const hit = supplierOptions.value.find((s) => s.id === id)
  if (hit) form.party_b = hit.name
}

function emptyRow(): Dict {
  // V2.1（N4）：行项必须绑定物料档案，故新增 product_id 与快照字段（含单位 uom_name）
  return { item_type: meta.value.item_types?.[0] ?? '采购', name: '', spec: '',
           product_id: null, product_code: '', product_name: '', uom_name: '',
           qty: null, unit_price: null, remark: '' }
}

/** V2.1（N4）：物料下拉（首次使用时加载一次） */
let productsLoaded = false

/** V2.6.1：树组件回传完整物料对象（与旧 onItemProductChange 等价） */
function onItemProductPicked(row: Dict, p: Dict | null) {
  if (!p) return
  row.product_code = p.code ?? ''
  row.product_name = p.name ?? ''
  row.uom_name = p.uom_name ?? ''
  if (!(row.name || '').trim()) row.name = p.name ?? ''
  if (!(row.spec || '').trim() && p.spec) row.spec = p.spec
  // CR-025：重新选择物料后单价跟随刷新
  row.unit_price = Number(p.default_price || 0)
}


function resetForm() {
  Object.assign(form, {
    contract_no: '', name: '', type: '采购', party_a: '', party_b: '',
    customer_id: null, supplier_id: null,
    sign_date: '', amount: 0, paid_amount: 0, received_amount: 0, status: '内部审批中',
    owner_name: '', remark: '', is_framework: false, parent_id: null, tags: [],
    items: [] as Dict[], subject_code: '',
    has_warranty: false, warranty_amount: null, warranty_rate: null,
    warranty_start: '', warranty_months: null,
  })
}

// 行项（MVP2 需求①）联动计算
/**
 * 空行判定：与 `save()` 提交时的过滤口径**必须一致**（两处漂移会导致
 * "界面说没行项、提交时却按行项算金额"这类难查的错）。
 */
function isBlankRow(r: Dict): boolean {
  // 与原先 `save()` 里 map 之后再 filter 的口径等价：文本 trim 后为空、数量/单价折算为 0
  return !(
    String(r.name ?? '').trim() || String(r.spec ?? '').trim()
    || Number(r.qty) || Number(r.unit_price) || String(r.remark ?? '').trim()
  )
}

/**
 * 是否有"有效行项"。
 *
 * ⚠️ 不能用 `form.items.length`：`openEdit()` 会给**没有行项的合同**补一个空行占位，
 * 按长度判断会得到 `true` → 金额框被禁用、合计按 0 算，编辑老合同一保存就把金额清零。
 */
const hasItems = computed(() => (form.items || []).some((r: Dict) => !isBlankRow(r)))

function rowTotal(r: Dict): number {
  return Number(((Number(r.qty) || 0) * (Number(r.unit_price) || 0)).toFixed(2))
}

const itemsTotal = computed(() => (form.items || []).reduce((s: number, r: Dict) => s + rowTotal(r), 0))

/**
 * 行项合计是**派生值**：有（有效）行项时「合同金额」必须实时等于它。
 *
 * 原先 `form.amount` 只在保存时（`save()` 里 `payload.amount = itemsTotal`）才被赋值，
 * 而金额输入框在有行项时是 `disabled` 的——于是改数量/单价/增删行后，框里始终停着
 * 打开表单时的旧值（新增时就是 0），用户看到"汇总金额没更新"。
 * 这里把显示值也与 `itemsTotal` 同步，保证**界面显示 = 提交给后端的金额**。
 */
watch(itemsTotal, (v) => {
  if (hasItems.value) form.amount = v
})

function addItemRow() {
  form.items.push(emptyRow())
}

function removeItemRow(i: number) {
  form.items.splice(i, 1)
}

// ---------- 自动编号预览（MVP3：类型码+主体码+年+月+6位序号，年度递增） ----------
const previewNo = ref('')
let noReq = 0

function defaultSubjectCode(): string {
  return String(meta.value.subjects?.[0]?.code ?? 'ZC')
}

async function refreshNumber() {
  const reqId = ++noReq
  if (editingId.value) {
    previewNo.value = ''
    return
  }
  const typeV = String(form.type || '')
  const subV = String(form.subject_code || '')
  if (!typeV || !subV) {
    previewNo.value = ''
    return
  }
  try {
    const r = await previewNumber(typeV, subV, form.sign_date || undefined)
    if (reqId === noReq && !editingId.value) previewNo.value = r.contract_no ?? ''
  } catch {
    if (reqId === noReq) previewNo.value = ''
  }
}

watch(() => [form.type, form.subject_code, form.sign_date], refreshNumber)

// 行项类型 = 系统级可配置列表（MVP2 需求① 补充）
const typesDlgVisible = ref(false)
const typesEdit = ref<string[]>([])
const typeNew = ref('')

function openTypes() {
  typesEdit.value = [...(meta.value.item_types ?? [])]
  typeNew.value = ''
  typesDlgVisible.value = true
}

function addType() {
  const v = typeNew.value.trim()
  if (!v) return
  if (!typesEdit.value.includes(v)) typesEdit.value.push(v)
  typeNew.value = ''
}

function removeType(i: number) {
  typesEdit.value.splice(i, 1)
}

async function saveTypes() {
  if (!typesEdit.value.length) {
    ElMessage.warning('至少保留一个类型')
    return
  }
  try {
    await saveItemTypes(typesEdit.value)
    meta.value = await getMeta()
    ElMessage.success('行项类型已更新')
    typesDlgVisible.value = false
  } catch (e) {
    ElMessage.error(apiError(e))
  }
}

function openNew() {
  editingId.value = null
  resetForm()
  form.subject_code = defaultSubjectCode()
  // 经办人默认当前登录账号（与单据页 `handler_user_id` 的默认口径一致）
  form.owner_name = auth.displayName
  form.type = String(meta.value.contract_type_defs?.find((t: Dict) => t.enabled && t.code !== 'OTH')?.label ?? meta.value.contract_types?.[0] ?? '采购/支出')
  previewNo.value = ''
  dialogVisible.value = true
  refreshNumber()
}

function openEdit(row: Dict) {
  editingId.value = row.id
  Object.assign(form, {
    contract_no: row.contract_no, name: row.name, type: row.type,
    party_a: row.party_a, party_b: row.party_b,
    customer_id: row.customer_id ?? null, supplier_id: row.supplier_id ?? null,
    sign_date: row.sign_date ?? '',
    amount: row.amount ?? 0, paid_amount: row.paid_amount ?? 0,
    received_amount: row.received_amount ?? 0,
    status: row.status, owner_name: row.owner_name ?? '',
    remark: row.remark ?? '', is_framework: row.is_framework,
    parent_id: row.parent_id ?? null, tags: [...(row.tags ?? [])],
    subject_code: row.subject_code ?? defaultSubjectCode(),
    items: (row.items ?? []).map((it: Dict) => ({
      item_type: it.item_type ?? '采购', name: it.name ?? '', spec: it.spec ?? '',
      product_id: it.product_id ?? null, product_code: it.product_code ?? '',
      product_name: it.product_name ?? '', uom_name: it.uom_name ?? '',
      qty: it.qty ?? null, unit_price: it.unit_price ?? null, remark: it.remark ?? '',
    })),
    has_warranty: row.has_warranty ?? false,
    warranty_amount: row.warranty_amount ?? null,
    warranty_rate: row.warranty_rate ?? null,
    warranty_start: row.warranty_start ?? '',
    warranty_months: row.warranty_months ?? null,
  })
  if (!form.items.length) form.items.push(emptyRow())
  previewNo.value = ''
  dialogVisible.value = true
}

async function save() {
  if (!form.contract_no && !editingId.value && !previewNo.value) {
    ElMessage.warning('合同编号生成失败：请确认已选择类型与我方公司')
    return
  }
  if (!form.contract_no && editingId.value) {
    ElMessage.warning('合同编号为空')
    return
  }
  if (!form.name) {
    ElMessage.warning('合同名称必填')
    return
  }
  if (!form.subject_code) {
    ElMessage.warning('请选择我方公司（主体）')
    return
  }
  const items = (form.items || [])
    // 过滤口径与 `hasItems` / `isBlankRow` 共用一处，避免"显示金额"与"提交行项"判断漂移
    .filter((r: Dict) => !isBlankRow(r))
    .map((r: Dict, i: number) => ({
      seq: i + 1,
      item_type: r.item_type || '采购',
      name: (r.name || '').trim(),
      spec: (r.spec || '').trim(),
      product_id: r.product_id ?? null,          // V2.1 / N4：行项必须绑定物料
      qty: Number(r.qty) || 0,
      unit_price: Number(r.unit_price) || 0,
      remark: (r.remark || '').trim(),
    }))
  // V2.1（N4，BR-V2.1-02）：行项必须选物料。前端给出**精确到行**的提示，
  // 服务端 `routers/contracts.py::_resolve_item_product` 仍会强制校验（前端不算边界）。
  const missingIdx = items.findIndex((r: Dict) => !r.product_id)
  if (missingIdx >= 0) {
    ElMessage.warning(`行项第 ${items[missingIdx].seq} 行：请选择物料档案`)
    return
  }
  saving.value = true
  try {
    const payload: Dict = {
      contract_no: editingId.value ? form.contract_no : previewNo.value,
      name: form.name, type: form.type,
      party_a: form.party_a, party_b: form.party_b,
      customer_id: isSalesType.value ? form.customer_id : null,
      supplier_id: isPurchaseType.value ? form.supplier_id : null,
      sign_date: form.sign_date || null,
      paid_amount: form.paid_amount, received_amount: form.received_amount,
      status: form.status,
      owner_name: form.owner_name || '', remark: form.remark || '',
      is_framework: form.is_framework, parent_id: form.parent_id,
      tags: form.tags, items,
      subject_code: form.subject_code || null,
      has_warranty: form.has_warranty,
      warranty_amount: form.warranty_amount, warranty_rate: form.warranty_rate,
      warranty_start: form.warranty_start || null, warranty_months: form.warranty_months,
    }
    payload.amount = items.length ? itemsTotal.value : form.amount // 有行项=Σ合计；无行项可手填
    if (editingId.value) await updateContract(editingId.value, payload)
    else await createContract(payload)
    ElMessage.success(editingId.value ? '已保存' : '已新增合同')
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

// ---------- 停用/恢复（AC-10/AC-15） ----------
async function remove(row: Dict) {
  try {
    const { value } = await ElMessageBox.prompt(`停用合同「${row.name}」，请输入原因（必填）：`, '停用确认', {
      confirmButtonText: '停用', cancelButtonText: '取消', inputValidator: (v: string) => (v && v.trim() ? true : '原因必填'),
    })
    await softDeleteContract(row.id, value.trim())
    ElMessage.success('已停用（30 天内可恢复）')
    load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') throw e
  }
}

async function restore(row: Dict) {
  try {
    await ElMessageBox.confirm(`恢复合同「${row.name}」？`, '恢复确认', { type: 'warning' })
    await restoreContract(row.id)
    ElMessage.success('已恢复')
    load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') throw e
  }
}

// ---------- 批量操作（T2-2） ----------
/**
 * 批量停用 / 批量恢复。
 *
 * ⚠️ 列宽约束：合同台账的列宽被 `10-layout.spec.ts` 以像素级断言锁定
 * （无横向滚动 + 操作列 ≤180px）。新增的选择列占 40px，因此把「合同编号」
 * 从 148px 收到 124px 并补 `show-overflow-tooltip` 抵消——编号列本身有富余，
 * 不会丢信息。改动此表列宽前务必重跑该 spec。
 */
const tableRef = ref()
const selected = ref<Dict[]>([])
const bulkLoading = ref(false)

function onSelectionChange(rows: Dict[]): void {
  selected.value = rows
}

function clearSelection(): void {
  tableRef.value?.clearSelection()
  selected.value = []
}

/** 逐条执行并汇总失败项——批量动作不能「一条失败就整体静默」 */
async function runBulk(
  rows: Dict[],
  label: string,
  action: (row: Dict) => Promise<unknown>,
): Promise<void> {
  bulkLoading.value = true
  const failed: string[] = []
  for (const row of rows) {
    try {
      await action(row)
    } catch {
      failed.push(row.contract_no || row.name)
    }
  }
  bulkLoading.value = false
  const okCount = rows.length - failed.length
  if (failed.length) {
    ElMessage.warning(`${label}完成：成功 ${okCount} 条，失败 ${failed.length} 条（${failed.join('、')}）`)
  } else {
    ElMessage.success(`${label}成功 ${okCount} 条`)
  }
  clearSelection()
  await load()
}

async function bulkDisable(): Promise<void> {
  const rows = selected.value.filter((r) => !r.deleted)
  if (!rows.length) {
    ElMessage.warning('所选合同中没有可停用的记录')
    return
  }
  try {
    const { value } = await ElMessageBox.prompt(
      `将停用选中的 ${rows.length} 份合同，请输入原因（必填）：`, '批量停用',
      {
        confirmButtonText: '批量停用', cancelButtonText: '取消',
        inputValidator: (v: string) => (v && v.trim() ? true : '原因必填'),
      },
    )
    await runBulk(rows, '批量停用', (row) => softDeleteContract(row.id, value.trim()))
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') throw e
  }
}

async function bulkRestore(): Promise<void> {
  const rows = selected.value.filter((r) => r.deleted)
  if (!rows.length) {
    ElMessage.warning('所选合同中没有可恢复的记录')
    return
  }
  try {
    await ElMessageBox.confirm(`确认恢复选中的 ${rows.length} 份合同？`, '批量恢复', { type: 'warning' })
    await runBulk(rows, '批量恢复', (row) => restoreContract(row.id))
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') throw e
  }
}

// ---------- 标签管理（T4，AC-13） ----------
const tagDialogVisible = ref(false)
const newTagName = ref('')

function apiError(e: any): string {
  return e?.response?.data?.detail || '操作失败'
}

async function addTag() {
  const name = newTagName.value.trim()
  if (!name) return
  try {
    await createTag(name)
    ElMessage.success('标签已新增')
    newTagName.value = ''
    await loadTags()
  } catch (e) {
    ElMessage.error(apiError(e))
  }
}

async function tagRename(tag: Dict) {
  try {
    const { value } = await ElMessageBox.prompt('新名称：', `重命名标签「${tag.name}」`, {
      inputValue: tag.name, confirmButtonText: '确定', cancelButtonText: '取消',
    })
    await renameTag(tag.id, value.trim())
    ElMessage.success('已重命名')
    await loadTags()
    load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(apiError(e))
  }
}

async function tagRemove(tag: Dict) {
  try {
    await ElMessageBox.confirm(`删除标签「${tag.name}」？它将从 ${tag.usage_count} 个合同上移除。`, '删除确认', { type: 'warning' })
    await deleteTag(tag.id)
    ElMessage.success('已删除')
    await loadTags()
    load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(apiError(e))
  }
}

// ---------- 批量导入（MVP2 需求②） ----------
const importDlgVisible = ref(false)
const importing = ref(false)
const importResult = ref<Dict | null>(null)

function openImportDialog() {
  importResult.value = null
  importDlgVisible.value = true
}

async function onImportFile(file: File) {
  importing.value = true
  importResult.value = null
  try {
    const res = await importContracts(file)
    importResult.value = res
    if (res.success > 0) load()
    if (res.fail === 0) ElMessage.success(`导入成功 ${res.success} 条`)
    else ElMessage.warning(`成功 ${res.success} 条，失败 ${res.fail} 条，详见下方报告`)
  } catch (e) {
    ElMessage.error(apiError(e))
  } finally {
    importing.value = false
  }
}

async function downloadTemplate() {
  try {
    // 同样需带令牌（contract.import）：blob 下载而非 window.open 裸 URL
    await downloadBlobFile('/import/template.xlsx', {}, '合同导入模板.xlsx')
  } catch (e) {
    ElMessage.error(apiError(e))
  }
}

// ---------- 详情（AC-01：详情可打开） ----------
const drawerVisible = ref(false)
const detail = ref<Dict>({})
const logs = ref<Dict[]>([])
const atts = ref<Dict[]>([])
const uploading = ref(false)
/** 关联单据区块（T-V2-24：采购线下游单据；接口未就绪时容错显示「—」） */
const relatedRef = ref<InstanceType<typeof RelatedDocs> | null>(null)

async function view(row: Dict) {
  detail.value = await fetchContract(row.id)
  logs.value = await fetchLogs(row.id)
  atts.value = await fetchAttachments(row.id)
  drawerVisible.value = true
  nextTick(() => relatedRef.value?.load())
}

async function onUpload(file: File) {
  if (!detail.value.id) return
  uploading.value = true
  try {
    await uploadAttachment(detail.value.id, file)
    ElMessage.success('上传成功')
    atts.value = await fetchAttachments(detail.value.id)
    logs.value = await fetchLogs(detail.value.id)
  } catch (e) {
    ElMessage.error(apiError(e))
  } finally {
    uploading.value = false
  }
}

async function onDeleteAttachment(row: Dict) {
  try {
    await ElMessageBox.confirm(`删除附件「${row.file_name}」？`, '删除确认', { type: 'warning' })
    await deleteAttachment(detail.value.id, row.id)
    ElMessage.success('已删除')
    atts.value = await fetchAttachments(detail.value.id)
    logs.value = await fetchLogs(detail.value.id)
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(apiError(e))
  }
}

function fmtSize(bytes: number): string {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function openAttachment(row: Dict) {
  try {
    // 预览/下载都要带令牌（附件接口按所属对象鉴权）：走 blob，不能用裸 URL 导航，
    // 否则浏览器导航请求不带 Authorization，后端回 401「未登录，请先登录」。
    if (canPreview(row.file_name)) await previewAttachment(row.id)
    else await downloadAttachment(row.id, row.file_name)
  } catch (e) {
    ElMessage.error(apiError(e))
  }
}

// 日期/金额格式化统一走 @/utils/format（T1-3）：原先此处各写一份，
// 且金额只设了 minimumFractionDigits，未限制小数位上限。

// ---------- 状态流转（T6，AC-04） ----------
const statusDlgVisible = ref(false)
const statusRow = ref<Dict>({})
const newStatus = ref('')
const statusNote = ref('')

function openStatus(row: Dict) {
  statusRow.value = row
  newStatus.value = row.status
  statusNote.value = ''
  statusDlgVisible.value = true
}

async function saveStatus() {
  if (!newStatus.value) {
    ElMessage.warning('请选择新状态')
    return
  }
  try {
    const payload: Dict = { status: newStatus.value }
    if (statusNote.value.trim()) payload.note = statusNote.value.trim()
    await updateContract(statusRow.value.id, payload)
    ElMessage.success('状态已更新')
    statusDlgVisible.value = false
    load()
  } catch (e) {
    ElMessage.error(apiError(e))
  }
}

// 变更历史字段中文标签（AC-12 展示友好）
const FIELD_LABELS: Record<string, string> = {
  contract_no: '合同编号', name: '合同名称', type: '类型', party_a: '甲方', party_b: '乙方',
  sign_date: '签订日期', effective_date: '生效日期', subject_matter: '标的物', amount: '合同金额',
  currency: '币种', paid_amount: '累计已付', status: '状态', owner_name: '经办人', remark: '备注',
  is_framework: '框架合同', parent_id: '所属框架', arrival_status: '到货状态',
  expected_arrival_date: '预计到货', has_warranty: '有质保金', warranty_amount: '质保金金额',
  warranty_rate: '质保金比例', warranty_start: '质保生效', warranty_months: '质保期限',
  warranty_end: '质保到期', warranty_released: '质保已释放', warranty_release_date: '释放日期',
  warranty_note: '质保备注', deleted: '删除', _tags: '标签', _items: '行项明细', _summary: '概要',
}

function fLabel(f: string): string {
  return FIELD_LABELS[f] ?? f
}

onMounted(async () => {
  meta.value = await getMeta()
  applyQueryFromUrl()      // 深链/刷新：先回填筛选，避免多打一次接口
  await Promise.all([load(), loadFrameworks(), loadTags(), loadPartyOptions(), loadOwnerOptions()])
})
</script>

<template>
  <div>
    <!-- 搜索区（完整组合筛选在 T5） -->
    <el-card shadow="never" class="mb">
      <div class="filter-bar">
      <el-form inline class="filter-form">
        <el-form-item label="关键词">
          <el-input v-model="query.keyword" placeholder="编号/名称/甲乙方" clearable style="width: 220px" @keyup.enter="page = 1; load()" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="query.type" filterable clearable placeholder="输入或选择类型" style="width: 140px">
            <el-option v-for="t in meta.contract_types" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="query.status" filterable clearable placeholder="输入或选择状态" style="width: 160px">
            <el-option v-for="s in meta.statuses" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="视图">
          <el-radio-group :model-value="viewMode" @change="onViewModeChange">
            <el-radio-button value="flat">平铺</el-radio-button>
            <el-radio-button value="tree">框架树</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="经办人">
          <el-input v-model="query.owner" clearable placeholder="经办人" style="width: 100px" @keyup.enter="page = 1; load()" />
        </el-form-item>
        <el-form-item label="标签">
          <el-select v-model="query.tags" multiple filterable collapse-tags collapse-tags-tooltip clearable placeholder="输入筛选/选择标签" style="width: 220px">
            <el-option v-for="t in tagOptions" :key="t.id" :label="t.name" :value="String(t.id)" />
          </el-select>
        </el-form-item>
        <el-form-item label="签订日期">
          <el-date-picker v-model="query.date_range" type="daterange" value-format="YYYY-MM-DD"
                          start-placeholder="起" end-placeholder="止" style="width: 240px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="page = 1; load()">查询</el-button>
          <el-button @click="resetQuery()">重置</el-button>
        </el-form-item>
      </el-form>
        <div class="filter-actions">
          <el-checkbox v-model="query.include_deleted" @change="page = 1; load()">显示已停用</el-checkbox>
          <el-button @click="openImportDialog()">导入</el-button>
          <el-button @click="router.push('/settings')">系统设置</el-button>
          <el-button type="success" @click="openNew()">＋ 新增合同</el-button>
        </div>
      </div>
    </el-card>

    <!-- 表格 -->
    <el-card shadow="never">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span>
            {{ isTree ? `框架树视图（共 ${viewRows.length} 行显示 / ${rows.length} 行数据）` : `合同台账（共 ${total} 条，含当前筛选）` }}
          </span>
          <el-button type="primary" plain :disabled="!rows.length && !total" @click="openExportDialog">导出 Excel（当前筛选）</el-button>
        </div>
      </template>

      <!-- 批量操作条（T2-2）：仅在有选择时出现，不占用常规视觉空间 -->
      <div v-if="selected.length" class="bulk-bar">
        <span class="bulk-count">已选 {{ selected.length }} 份合同</span>
        <el-button type="danger" size="small" :loading="bulkLoading" @click="bulkDisable">批量停用</el-button>
        <el-button type="success" size="small" :loading="bulkLoading" @click="bulkRestore">批量恢复</el-button>
        <el-button link size="small" @click="clearSelection">取消选择</el-button>
      </div>

      <el-table ref="tableRef" v-loading="loading" :data="viewRows" border stripe size="small"
                :row-class-name="isTree ? rowClass : undefined" @row-dblclick="view"
                @selection-change="onSelectionChange">
        <el-table-column type="selection" width="40" />
        <el-table-column v-if="isTree" width="44" align="center">
          <template #default="{ row }">
            <span v-if="row.tree === 'f'" class="fw-icon" @click.stop="toggleFw(row.id)">
              {{ collapsedIds.includes(row.id) ? '▸' : '▾' }}
            </span>
            <span v-else-if="row.tree === 'c'" class="child-icon">↳</span>
          </template>
        </el-table-column>
        <el-table-column prop="contract_no" label="合同编号" width="124" show-overflow-tooltip />
        <!-- 名称列宽 192 → 168：为批量选择列（40px）腾出空间。
             实测容器 1146px、列总 1162px（溢出 16px），回收 24px 后留 8px 余量。
             改动此表任何列宽前，务必重跑 10-layout.spec.ts 的像素断言。 -->
        <el-table-column label="合同名称 / 标签" min-width="168">
          <template #default="{ row }">
            <div class="name-cell">
              <span class="name-text" :title="row.name">{{ row.name }}</span>
              <!-- 标签并进名称列：单独一列会因多个 el-tag 平铺把行高撑成两行 -->
              <el-tooltip v-if="row.tags && row.tags.length" :content="row.tags.join('、')" placement="top">
                <el-tag size="small" class="name-tag">{{ row.tags[0] }}</el-tag>
              </el-tooltip>
              <span v-if="row.tags && row.tags.length > 1" class="more-tag">+{{ row.tags.length - 1 }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="type" label="类型" width="84" />
        <el-table-column label="甲方" min-width="88" show-overflow-tooltip>
          <template #default="{ row }">
            <span>{{ row.party_a || '—' }}</span>
            <el-tag v-if="row.customer_id" size="small" type="success" class="ml4">档案</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="乙方" min-width="88" show-overflow-tooltip>
          <template #default="{ row }">
            <span>{{ row.party_b || '—' }}</span>
            <el-tag v-if="row.supplier_id" size="small" type="warning" class="ml4">档案</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="金额" width="92" align="right">
          <template #default="{ row }">{{ fmtMoney(row.amount) }}</template>
        </el-table-column>
        <el-table-column label="已付（比例）" width="128" align="right">
          <template #default="{ row }">
            <!-- V2.5+：同一列按合同类型取数 —— 销售/收入看「累计已收」（收款单），其余看「累计已付」（付款单） -->
            <span>{{ fmtMoney(rowAmount(row)) }}</span>
            <span class="ratio">
              {{ rowRatio(row) !== null && rowRatio(row) !== undefined
                ? Number(rowRatio(row)).toFixed(1) + '%' : '—' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="80" />
        <el-table-column prop="owner_name" label="经办人" width="70" />
        <el-table-column label="操作" width="176" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="view(row)">详情</el-button>
            <template v-if="row.deleted">
              <el-button link type="success" size="small" @click="restore(row)">恢复</el-button>
            </template>
            <template v-else>
              <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
              <el-button link type="warning" size="small" @click="openStatus(row)">状态</el-button>
              <el-button link type="danger" size="small" @click="remove(row)">停用</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-if="!isTree"
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        background
        layout="total, prev, pager, next, sizes"
        class="mt"
        @current-change="load"
        @size-change="page = 1; load()"
      />
      <el-alert v-else type="info" :closable="false" class="mt" title="框架树为展示视图：搜索/筛选/导出仍按平铺结果处理；子合同行自动附带【框架合同】标识。" />
    </el-card>

    <!-- 新增/编辑弹窗 -->
    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑合同' : '新增合同'" width="min(1080px, 92vw)" destroy-on-close>
      <el-form :model="form" label-width="90px">
        <el-divider content-position="left">基本信息</el-divider>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="合同编号">
            <el-input :model-value="editingId ? form.contract_no : previewNo" readonly
                      :placeholder="editingId ? '' : '自动生成中…'" />
          </el-form-item></el-col>
          <el-col :span="12"><el-form-item label="合同名称" required><el-input v-model="form.name" /></el-form-item></el-col>
          <el-col :span="6"><el-form-item label="类型" required>
            <el-select v-model="form.type" filterable style="width: 100%">
              <el-option v-for="t in meta.contract_types" :key="t" :label="t" :value="t" />
            </el-select>
          </el-form-item></el-col>
          <el-col :span="6"><el-form-item label="我方公司">
            <el-select v-model="form.subject_code" filterable style="width: 100%">
              <el-option v-for="s in meta.subjects" :key="s.code" :label="`${s.name} (${s.code})`" :value="s.code" />
            </el-select>
          </el-form-item></el-col>
          <el-col :span="6"><el-form-item label="签订日期"><el-date-picker v-model="form.sign_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" /></el-form-item></el-col>
          <el-col :span="6"><el-form-item label="经办人">
            <!-- 数据源与单据页一致：`/api/master/options/user`（仅启用账号）；
                 绑姓名而非 id —— `Contract` 只有文本字段 `owner_name`（见 ownerChoices 注释） -->
            <el-select v-model="form.owner_name" filterable clearable placeholder="选择系统用户"
                       style="width: 100%">
              <el-option v-for="u in ownerChoices" :key="u.id"
                         :label="u.username ? `${u.name}（${u.username}）` : u.name" :value="u.name" />
            </el-select>
          </el-form-item></el-col>
          <el-col :span="12"><el-form-item label="甲方">
            <el-select v-if="isSalesType" v-model="form.customer_id" filterable clearable
                       placeholder="选择客户档案（销售合同）" style="width: 100%"
                       @change="onCustomerChange">
              <el-option v-for="c in customerOptions" :key="c.id"
                         :label="`${c.name}（${c.code}）`" :value="c.id" />
            </el-select>
            <el-input v-else v-model="form.party_a" placeholder="甲方（其他类型可用纯文本）" />
          </el-form-item></el-col>
          <el-col :span="12"><el-form-item label="乙方">
            <el-select v-if="isPurchaseType" v-model="form.supplier_id" filterable clearable
                       placeholder="选择供应商档案（采购合同）" style="width: 100%"
                       @change="onSupplierChange">
              <el-option v-for="s in supplierOptions" :key="s.id"
                         :label="`${s.name}（${s.code}）`" :value="s.id" />
            </el-select>
            <el-input v-else v-model="form.party_b" placeholder="乙方（其他类型可用纯文本）" />
          </el-form-item></el-col>
          <el-col v-if="form.customer_id || form.supplier_id" :span="24">
            <el-form-item label="档案快照">
              <span class="gray">
                甲方：{{ form.party_a || '—' }}；乙方：{{ form.party_b || '—' }}
                （档案变更不影响已保存的名称快照，可理解为签约时的对方名称）
              </span>
            </el-form-item>
          </el-col>
          <el-col :span="24" v-if="!editingId">
            <el-form-item label="编号规则"><span class="gray">{{ meta.numbering_hint }}；选择类型/主体/签订日期后自动生成</span></el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">标的物行项（可增删行 · 总价=数量×单价 · 金额自动汇总）</el-divider>
        <el-table :data="form.items" size="small" border>
          <el-table-column label="序号" width="50">
            <template #default="{ $index }">{{ $index + 1 }}</template>
          </el-table-column>
          <el-table-column label="类型" width="110">
            <template #default="{ row }">
              <el-select v-model="row.item_type" filterable size="small" style="width: 100%">
                <el-option v-for="t in meta.item_types" :key="t" :label="t" :value="t" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="物料" min-width="180">
            <!-- V2.1 / N4：合同行项必须绑定系统物料档案（选中后带出名称/规格/默认单价） -->
            <template #default="{ row }">
              <!-- V2.6.1 / CR-021：与单据行项共用 ProductTreeSelect（树形展开 + 悬停档案信息） -->
              <ProductTreeSelect v-model="row.product_id"
                                 :fallback-label="row.product_name
                                   ? `${row.product_name}（${row.product_code || row.product_id}）` : ''"
                                 @change="(p: Dict | null) => onItemProductPicked(row, p)" />
            </template>
          </el-table-column>
          <el-table-column label="名称" min-width="150">
            <template #default="{ row }"><el-input v-model="row.name" size="small" placeholder="行项名称" /></template>
          </el-table-column>
          <el-table-column label="规格型号" min-width="110">
            <template #default="{ row }"><el-input v-model="row.spec" size="small" placeholder="如 X-2000" /></template>
          </el-table-column>
          <!-- V2.5：单位只读列，随所选物料带出（口径同单据行项 `DocItemsTable`；
               编辑旧合同时由后端 `/api/contracts` 的 items 返回 `uom_name`） -->
          <!-- V2.6：数量列移到单位前（只调顺序；单位仍是随物料带出的只读列） -->
          <el-table-column label="数量" width="110">
            <template #default="{ row }"><el-input-number v-model="row.qty" :min="0" :precision="3" :controls="false" size="small" style="width: 100%" /></template>
          </el-table-column>
          <el-table-column label="单位" width="80">
            <template #default="{ row }"><span>{{ row.uom_name || '—' }}</span></template>
          </el-table-column>
          <el-table-column label="单价" width="120">
            <template #default="{ row }"><el-input-number v-model="row.unit_price" :min="0" :precision="4" :controls="false" size="small" style="width: 100%" /></template>
          </el-table-column>
          <el-table-column label="总价" width="120" align="right">
            <template #default="{ row }"><span>{{ fmtMoney(rowTotal(row)) }}</span></template>
          </el-table-column>
          <el-table-column label="备注" min-width="140">
            <template #default="{ row }"><el-input v-model="row.remark" size="small" placeholder="备注" /></template>
          </el-table-column>
          <el-table-column label="操作" width="64" align="center">
            <template #default="{ $index }">
              <el-button link type="danger" size="small" @click="removeItemRow($index)">删</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="mt" style="display: flex; justify-content: space-between; align-items: center">
          <div>
            <el-button size="small" @click="addItemRow()">＋ 增加一行</el-button>
            <span class="gray" style="margin-left: var(--ctms-gap-sm)">行项为空时金额可手填（框架/预估合同）</span>
          </div>
          <div class="totalbar">
            <span>行项合计（{{ form.items.length }} 行）</span>
            <b>￥{{ fmtMoney(itemsTotal) }}</b>
          </div>
        </div>

        <el-divider content-position="left">金额与收付款（比例 = 已付/已收 ÷ 金额）</el-divider>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="合同金额">
              <el-input-number v-model="form.amount" :min="0" :precision="2" :controls="false"
                               :disabled="hasItems" :placeholder="hasItems ? '行项合计' : '0.00'" style="width: 100%" />
              <span v-if="hasItems" class="gray" style="line-height:1">＝行项合计</span>
            </el-form-item>
          </el-col>
          <!-- V2.5+：字段随合同方向切换 —— 销售/收入类录「累计已收」（收款单回写口径），其余录「累计已付」 -->
          <el-col :span="8">
            <el-form-item :label="isSalesType ? '累计已收' : '累计已付'">
              <el-input-number v-if="isSalesType" v-model="form.received_amount"
                               :min="0" :precision="2" :controls="false" style="width: 100%" />
              <el-input-number v-else v-model="form.paid_amount"
                               :min="0" :precision="2" :controls="false" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8"><el-form-item label="状态"><el-select v-model="form.status" filterable style="width: 100%"><el-option v-for="s in meta.statuses" :key="s" :label="s" :value="s" /></el-select></el-form-item></el-col>
        </el-row>
        <el-divider content-position="left">质保金（BR5 · 到期日自动计算并提醒）</el-divider>
        <el-row :gutter="12">
          <el-col :span="24">
            <el-form-item label="含质保金">
              <el-switch v-model="form.has_warranty" active-text="是" inactive-text="否" />
              <span v-if="form.has_warranty" class="gray" style="margin-left: var(--ctms-gap-sm)">录比例自动换算金额（或反之）</span>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row v-if="form.has_warranty" :gutter="12">
          <el-col :span="6"><el-form-item label="质保金额(元)"><el-input-number v-model="form.warranty_amount" :min="0" :precision="2" :controls="false" style="width: 100%" /></el-form-item></el-col>
          <el-col :span="6"><el-form-item label="比例(%)"><el-input-number v-model="form.warranty_rate" :min="0" :max="100" :precision="2" :controls="false" style="width: 100%" /></el-form-item></el-col>
          <el-col :span="6"><el-form-item label="生效日期"><el-date-picker v-model="form.warranty_start" type="date" value-format="YYYY-MM-DD" style="width: 100%" /></el-form-item></el-col>
          <el-col :span="6"><el-form-item label="期限(月)"><el-input-number v-model="form.warranty_months" :min="1" :max="240" :controls="false" style="width: 100%" /></el-form-item></el-col>
        </el-row>

        <el-divider content-position="left">框架与备注</el-divider>
        <el-row :gutter="12">
          <el-col :span="8"><el-form-item label="框架合同"><el-switch v-model="form.is_framework" active-text="是" inactive-text="否" /></el-form-item></el-col>
          <el-col :span="16">
            <el-form-item v-if="!form.is_framework" label="所属框架">
              <el-select v-model="form.parent_id" clearable placeholder="无（独立合同）" style="width: 100%">
                <el-option v-for="f in frameworks" :key="f.id" :label="`${f.contract_no} · ${f.name}`" :value="f.id" />
              </el-select>
            </el-form-item>
            <el-form-item v-else label="说明"><span class="gray">作为框架合同：其他合同可挂到其下（BR6）</span></el-form-item>
          </el-col>
          <el-col :span="24"><el-form-item label="标签">
            <el-select v-model="form.tags" multiple filterable allow-create default-first-option clearable
                       placeholder="选择已有标签，或输入后回车新建" style="width: 100%">
              <el-option v-for="t in tagOptions" :key="t.id" :label="t.name" :value="t.name" />
            </el-select>
          </el-form-item></el-col>
          <el-col :span="24"><el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="2" /></el-form-item></el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 导出设置（MVP2 需求③） -->
    <el-dialog v-model="exportDlgVisible" title="导出 Excel · 选择导出项（重要列默认勾选）" width="min(760px, 92vw)">
      <div class="mb"><b>📌 重要列（默认勾选）</b></div>
      <el-checkbox-group v-model="exportCols" class="colwrap mb" @change="exportRemember && rememberExportCols()">
        <el-checkbox v-for="c in impExportCols" :key="c.key" :value="c.key" border>{{ c.label }}</el-checkbox>
      </el-checkbox-group>
      <div class="mb"><b>🗂 次要列（默认不勾）</b></div>
      <el-checkbox-group v-model="exportCols" class="colwrap mb" @change="exportRemember && rememberExportCols()">
        <el-checkbox v-for="c in optExportCols" :key="c.key" :value="c.key" border>{{ c.label }}</el-checkbox>
      </el-checkbox-group>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <div>
          <el-button size="small" @click="setAllExportCols">全选</el-button>
          <el-button size="small" @click="clearExportCols">清空</el-button>
          <el-button size="small" type="warning" plain @click="resetExportCols">恢复默认</el-button>
          <el-switch v-model="exportRemember" size="small" style="margin-left: 12px" active-text="记住本次选择" />
        </div>
        <span class="totalbar">将导出 <b>{{ exportCols.length }}</b> 列</span>
      </div>
      <template #footer>
        <el-button @click="exportDlgVisible = false">取消</el-button>
        <el-button type="primary" @click="doExport">导出（当前筛选）</el-button>
      </template>
    </el-dialog>

    <!-- 批量导入（MVP2 需求②：仅新建） -->
    <el-dialog v-model="importDlgVisible" title="批量导入合同（仅新建 · 按系统模板）" width="min(720px, 92vw)">
      <el-alert type="info" :closable="false" class="mb"
        title="① 先下载模板填写 → ② 上传 → ③ 看结果。错误行（编号重复/格式错误）整条跳过、不落库。" />
      <div class="mb" style="display: flex; gap: 8px">
        <el-button @click="downloadTemplate">⬇ 下载系统导入模板(.xlsx)</el-button>
        <el-upload :show-file-list="false" :http-request="(o: any) => onImportFile(o.file as File)"
                   accept=".xlsx,.xlsm" :disabled="importing">
          <el-button type="primary" :loading="importing">选择文件并导入</el-button>
        </el-upload>
      </div>
      <template v-if="importResult">
        <el-alert v-if="importResult.fail === 0" type="success" :closable="false" class="mb"
          :title="`导入完成：成功 ${importResult.success} 条`" />
        <el-alert v-else type="warning" :closable="false" class="mb"
          :title="`导入完成：成功 ${importResult.success} 条，失败 ${importResult.fail} 条（已跳过，不影响库内数据）`" />
        <el-table v-if="importResult.errors?.length" :data="importResult.errors" size="small" border max-height="280">
          <el-table-column prop="row" label="Excel 行" width="80" align="center" />
          <el-table-column prop="contract_no" label="合同编号" width="150" />
          <el-table-column prop="reason" label="失败原因" min-width="260" show-overflow-tooltip />
        </el-table>
      </template>
    </el-dialog>

    <!-- 状态流转（T6，AC-04） -->
    <el-dialog v-model="statusDlgVisible" :title="`状态流转 · ${statusRow.contract_no ?? ''}`" width="min(460px, 92vw)">
      <el-form label-width="80px">
        <el-form-item label="当前状态"><el-tag>{{ statusRow.status }}</el-tag></el-form-item>
        <el-form-item label="新状态">
          <el-select v-model="newStatus" filterable style="width: 100%">
            <el-option v-for="s in meta.statuses" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注（可选）">
          <el-input v-model="statusNote" type="textarea" :rows="2" placeholder="流转说明/原因" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="statusDlgVisible = false">取消</el-button>
        <el-button type="primary" @click="saveStatus">确认流转</el-button>
      </template>
    </el-dialog>

    <!-- 系统字典：行项类型（MVP2 · 系统级可配置） -->
    <el-dialog v-model="typesDlgVisible" title="系统字典 · 行项类型（新增/编辑合同时下拉选用）" width="min(520px, 92vw)">
      <div class="mb" style="display: flex; gap: 8px">
        <el-input v-model="typeNew" placeholder="新增类型，回车确认" @keyup.enter="addType" />
        <el-button type="primary" @click="addType">新增</el-button>
      </div>
      <el-table :data="typesEdit" size="small" border>
        <el-table-column label="类型名称" min-width="200">
          <template #default="{ row, $index }">
            <el-input v-model="typesEdit[$index]" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ $index }">
            <el-button link type="danger" @click="removeType($index)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <p class="gray" style="margin-bottom:0">修改后立即生效并影响下拉选项；已有行项的类型名不受影响。</p>
      <template #footer>
        <el-button @click="typesDlgVisible = false">取消</el-button>
        <el-button type="primary" @click="saveTypes">保存</el-button>
      </template>
    </el-dialog>

    <!-- 标签管理（T4，AC-13） -->
    <el-dialog v-model="tagDialogVisible" title="标签管理" width="min(520px, 92vw)">
      <div class="mb" style="display: flex; gap: 8px">
        <el-input v-model="newTagName" placeholder="新标签名称，回车确认" @keyup.enter="addTag" />
        <el-button type="primary" @click="addTag">新增</el-button>
      </div>
      <el-table :data="tagOptions" size="small" border>
        <el-table-column label="标签" min-width="160">
          <template #default="{ row }">
            <el-tag :color="row.color" style="color:#fff;border:none">{{ row.name }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="usage_count" label="使用合同数" width="100" align="center" />
        <el-table-column label="操作" width="130">
          <template #default="{ row }">
            <el-button link type="primary" @click="tagRename(row)">改名</el-button>
            <el-button link type="danger" @click="tagRemove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 详情抽屉 -->
    <el-drawer v-model="drawerVisible" :title="`合同详情 · ${detail.contract_no ?? ''}`" size="min(640px, 96vw)">
      <template v-if="detail.id">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="合同名称" :span="2">{{ detail.name }}</el-descriptions-item>
          <el-descriptions-item label="类型">{{ detail.type }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ detail.status }}</el-descriptions-item>
          <el-descriptions-item label="甲方">{{ detail.party_a || '—' }}</el-descriptions-item>
          <el-descriptions-item label="乙方">{{ detail.party_b || '—' }}</el-descriptions-item>
          <el-descriptions-item label="签订日期">{{ fmtDate(detail.sign_date) }}</el-descriptions-item>
          <el-descriptions-item label="经办人">{{ detail.owner_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="标的物" :span="2">{{ detail.subject_matter || '—' }}</el-descriptions-item>
          <el-descriptions-item label="合同金额">{{ fmtMoney(detail.amount) }}</el-descriptions-item>
          <el-descriptions-item :label="isSalesRow(detail.type) ? '累计已收' : '累计已付'">
            {{ fmtMoney(rowAmount(detail)) }}
          </el-descriptions-item>
          <el-descriptions-item :label="isSalesRow(detail.type) ? '收款比例' : '付款比例'">
            {{ rowRatio(detail) !== null ? Number(rowRatio(detail)).toFixed(1) + '%' : '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="所属框架">{{ detail.parent_no || '—' }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.is_framework" label="子合同" :span="2">
            共 {{ detail.children_count }} 份，金额合计 {{ fmtMoney(detail.children_amount_sum) }}
          </el-descriptions-item>
          <el-descriptions-item label="标签" :span="2">
            <el-tag v-for="t in detail.tags" :key="t" size="small" class="mr-4">{{ t }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.has_warranty" label="质保" :span="2">
            金额 {{ fmtMoney(detail.warranty_amount) }}（{{ detail.warranty_rate }}%）· 到期 {{ fmtDate(detail.warranty_end) }}
          </el-descriptions-item>
        </el-descriptions>

        <template v-if="detail.is_framework">
          <el-divider content-position="left">子合同列表（共 {{ detail.children_count ?? 0 }} 份）</el-divider>
          <el-table v-if="detail.children?.length" :data="detail.children" size="small" border>
            <el-table-column prop="contract_no" label="编号" width="130" />
            <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip />
            <el-table-column label="金额" width="110" align="right">
              <template #default="{ row }">{{ fmtMoney(row.amount) }}</template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="110" />
            <el-table-column prop="owner_name" label="经办人" width="80" />
          </el-table>
          <el-empty v-else description="暂无子合同" :image-size="60" />
        </template>

        <!-- 关联单据（T-V2-24）：采购线只读区块；接口未就绪时显示「—」 -->
        <RelatedDocs ref="relatedRef" :contract-id="Number(detail.id)" />

        <el-divider content-position="left">附件（T7 · 上传/下载/预览，PDF 与图片可预览）</el-divider>
        <div class="mb">
          <el-upload
            :show-file-list="false"
            :http-request="(o: any) => onUpload(o.file as File)"
            :before-upload="(f: File) => f.size <= 20 * 1024 * 1024 || (ElMessage.error('附件不能超过 20MB'), false)"
            accept=".pdf,.doc,.docx,.xls,.xlsx,.png,.jpg,.jpeg,.gif,.txt"
          >
            <el-button type="primary" :loading="uploading" plain>上传附件</el-button>
          </el-upload>
        </div>
        <el-table v-if="atts.length" :data="atts" size="small" border>
          <el-table-column prop="file_name" label="文件名" min-width="180" show-overflow-tooltip />
          <el-table-column label="大小" width="90">
            <template #default="{ row }">{{ fmtSize(row.size_bytes) }}</template>
          </el-table-column>
          <el-table-column label="上传时间" width="110">
            <template #default="{ row }">{{ fmtDate(row.uploaded_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="150">
            <template #default="{ row }">
              <el-button link type="primary" @click="openAttachment(row)">
                {{ canPreview(row.file_name) ? '预览' : '下载' }}
              </el-button>
              <el-button link type="danger" @click="onDeleteAttachment(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else-if="!uploading" description="暂无附件" :image-size="60" />

        <el-divider content-position="left">变更历史（时间 · 字段 · 旧值 → 新值）</el-divider>
        <el-timeline v-if="logs.length">
          <el-timeline-item v-for="lg in logs" :key="lg.id" :timestamp="fmtDateTime(lg.created_at)" placement="top">
            <div v-if="lg.field_name === '_summary' && lg.new_value">变更字段：{{ lg.new_value }}</div>
            <div v-else-if="lg.field_name === '_summary'"><b>新增合同</b></div>
            <div v-else-if="lg.field_name === 'deleted'"><b>停用/恢复</b>：{{ lg.note }}</div>
            <div v-else-if="lg.field_name === '备注'"><b>备注</b>：{{ lg.new_value }}</div>
            <div v-else><b>{{ fLabel(lg.field_name) }}</b>：{{ lg.old_value ?? '（空）' }} → {{ lg.new_value ?? '（空）' }}</div>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="暂无变更记录" :image-size="60" />
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.mb { margin-bottom: var(--ctms-gap); }
.mt { margin-top: var(--ctms-gap); }
/* 批量操作条（T2-2） */
.bulk-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  padding: 6px 10px;
  background: #f2f6fc;
  border: 1px solid #d9ecff;
  border-radius: 4px;
}
.bulk-count { color: var(--ctms-text-secondary); font-size: var(--ctms-fs-sm); }
/*
 * 筛选区布局：用 flex 换行取代原来的 `float: right`。
 * float 在 inline 表单里换行后会脱离对齐基准，把「显示已停用/导入/系统设置/新增合同」
 * 推到错位位置；改成 flex 后：宽屏时按钮组自动靠右，窄屏换行时回到左对齐，不再悬空。
 */
.filter-bar { display: flex; flex-wrap: wrap; align-items: flex-start; column-gap: 16px; }
.filter-form { flex: 1 1 720px; min-width: 0; }
.filter-form :deep(.el-form-item) { margin-right: 16px; }
.filter-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-left: auto;
  margin-bottom: 18px;   /* 与 el-form-item 的下边距保持一致，保证同一行基线对齐 */
}
@media (max-width: 1400px) {
  .filter-actions { margin-left: 0; }
}
.mr-4 { margin-right: 4px; }
/* 「已付（比例）」合并列里的比例，弱化显示 */
.ratio { margin-left: 6px; color: var(--ctms-text-muted); font-size: var(--ctms-fs-xs); }
/* 名称列：名称超出用省略号（title 显示全文），标签跟在后面不换行 */
.name-cell { display: flex; align-items: center; gap: 6px; min-width: 0; }
.name-text { flex: 0 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.name-tag { flex: 0 0 auto; }
/* 标签的「+N」，鼠标悬停可看全部标签 */
.more-tag { flex: 0 0 auto; color: var(--ctms-text-muted); font-size: var(--ctms-fs-xs); cursor: default; }
.colwrap :deep(.el-checkbox) { margin-right: var(--ctms-gap-sm); margin-bottom: 6px; }
.gray { color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); }
.totalbar { font-size: var(--ctms-fs-sm); color: var(--ctms-text-secondary); }
.totalbar b { font-size: var(--ctms-fs-md); color: var(--ctms-danger-text); margin-left: 6px; }
.fw-icon { cursor: pointer; color: var(--ctms-primary); font-size: var(--ctms-fs-base); }
.child-icon { color: #c0c4cc; }
:deep(.tree-child-row td) { background: #fafbfd; }
:deep(.tree-fw-row td) { font-weight: 600; background: #ecf5ff; }
</style>
