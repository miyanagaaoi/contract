<script setup lang="ts">
/**
 * 询价报价（CR-044，部门内部版）：询价单 + 代录各家报价 + 比价报表。
 * 纯内部：不开放外部账号；不与采购流程联动。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DataAnalysis, Download, Plus, Search } from '@element-plus/icons-vue'

import {
  awardRfq, closeRfq, compareRfq, createRfq, deleteRfq, downloadBlobFile,
  fetchMasterOptions,
  fetchRfqDetail, fetchRfqPrintTemplate, fetchRfqs, publishRfq, saveRfqQuote,
  updateRfq, type Dict,
} from '@/api'
import { fmtMoney, fmtQty } from '@/utils/format'

const loading = ref(false)
const rows = ref<Dict[]>([])
const total = ref(0)
const query = ref<Dict>({ keyword: '', status: '', page: 1, page_size: 20 })
const statuses = ref<Dict[]>([
  { code: 'draft', label: '草稿' }, { code: 'open', label: '询价中' },
  { code: 'closed', label: '已截止' },
])

async function load() {
  loading.value = true
  try {
    const data = await fetchRfqs(query.value)
    rows.value = (data.items || []) as Dict[]
    total.value = data.total || 0
  } finally { loading.value = false }
}

// ---------------- 新建 / 编辑 ----------------
const formVisible = ref(false)
const formRef = ref<Dict>({ title: '', project: '', deadline: '', remark: '',
  responsibility_dept: '', budget_amount: null })
const lines = ref<Dict[]>([])
const editId = ref<number | null>(null)

function openCreate() {
  editId.value = null
  formRef.value = { title: '', project: '', deadline: '', remark: '',
    responsibility_dept: '', budget_amount: null }
  lines.value = [{ material_name: '', spec: '', unit: '', qty: 1, need_date: '' }]
  formVisible.value = true
}

async function openEdit(row: Dict) {
  const detail = await fetchRfqDetail(row.id)
  editId.value = row.id
  formRef.value = { title: detail.title, project: detail.project || '',
    deadline: (detail.deadline || '').replace(' ', 'T'), remark: detail.remark || '',
    responsibility_dept: detail.responsibility_dept || '',
    budget_amount: detail.budget_amount ?? null }
  lines.value = (detail.lines || []).map((l: Dict) => ({
    material_name: l.material_name, spec: l.spec || '', unit: l.unit || '',
    qty: l.qty, need_date: l.need_date || '',
  }))
  formVisible.value = true
}

function addLine() { lines.value.push({ material_name: '', spec: '', unit: '', qty: 1, need_date: '' }) }
function delLine(i: number) { lines.value.splice(i, 1) }

async function saveForm() {
  const payload = {
    ...formRef.value,
    deadline: formRef.value.deadline || null,
    lines: lines.value.filter((l) => String(l.material_name || '').trim()),
  }
  if (!payload.lines.length) { ElMessage.warning('至少填写一行询价明细'); return }
  if (editId.value) await updateRfq(editId.value, payload)
  else await createRfq(payload)
  ElMessage.success(editId.value ? '已保存' : '已创建草稿')
  formVisible.value = false
  await load()
}

// ---------------- 详情 / 比价 ----------------
const detailVisible = ref(false)
const detail = ref<Dict>({})
const cmp = ref<Dict>({ rows: [], supplier_totals: [] })
// ---- 比价对比表（交叉表，参考 xunjia 询价项目的统计报表设计）----
const matrixSuppliers = computed(() => (detail.value.quotes || []) as Dict[])
/** 各供应商拿下“该行最低价”的次数（列头展示，一眼看出谁最有竞争力） */
const winCount = computed(() => {
  const out: Record<number, number> = {}
  for (const row of cmp.value.rows || []) {
    const low = row.lowest
    if (low) out[low.supplier_id] = (out[low.supplier_id] || 0) + 1
  }
  return out
})
/** 每行：按供应商取报价，并补统计列（最低/最高/均价/价差率） */
const matrixRows = computed(() => (cmp.value.rows || []).map((row: Dict) => {
  const offers = row.offers || []
  const prices = offers.map((o: Dict) => Number(o.unit_price))
  const max = prices.length ? Math.max(...prices) : null
  const avg = prices.length ? prices.reduce((a: number, b: number) => a + b, 0) / prices.length : null
  const spread = row.lowest && max ? ((max - row.lowest.unit_price) / row.lowest.unit_price * 100) : null
  const bySupplier: Record<number, Dict> = {}
  for (const o of offers) bySupplier[o.supplier_id] = o
  return { ...row, bySupplier, max, avg, spread, count: offers.length }
}))
/** 比价结论：按“各行最低价 × 数量”合计排序，给出建议供应商 */
const conclusion = computed(() => {
  const totals = (cmp.value.supplier_totals || []) as Dict[]
  const sorted = [...totals].sort((a, b) => Number(a.amount) - Number(b.amount))
  if (!sorted.length) return null
  return { best: sorted[0], count: sorted.length,
           gap: sorted.length > 1 ? Number(sorted[1].amount) - Number(sorted[0].amount) : null }
})

const suppliers = ref<Dict[]>([])

async function openDetail(row: Dict) {
  detail.value = await fetchRfqDetail(row.id)
  cmp.value = await compareRfq(row.id)
  detailVisible.value = true
}

// ---------------- 录入报价 ----------------
const quoteVisible = ref(false)
const quoteRef = ref<Dict>({ supplier_id: null, quote_date: '', contact_name: '',
  contact_phone: '', channel: '微信', remark: '', delivery_period: '',
  payment_terms: '', after_sales: '', price_score: null, quality_score: null,
  service_score: null })
const quoteLines = ref<Dict[]>([])

async function ensureSuppliers() {
  if (!suppliers.value.length) suppliers.value = await fetchMasterOptions('supplier')
}

function openQuote() {
  quoteRef.value = { supplier_id: null, quote_date: new Date().toISOString().slice(0, 10),
    contact_name: '', contact_phone: '', channel: '微信', remark: '',
    delivery_period: '', payment_terms: '', after_sales: '',
    price_score: null, quality_score: null, service_score: null }
  quoteLines.value = (detail.value.lines || []).map((l: Dict) => ({
    line_id: l.id, unit_price: 0, tax_rate: 13, moq: null, lead_days: null, remark: '',
  }))
  quoteVisible.value = true
  ensureSuppliers()
}

/** 选供应商后回填已有报价（再次录入即修改） */
function onSupplierChange(sid: number) {
  const q = (detail.value.quotes || []).find((x: Dict) => x.supplier_id === sid)
  if (!q) return
  quoteRef.value = { ...quoteRef.value, ...q, supplier_id: sid,
    quote_date: q.quote_date || quoteRef.value.quote_date }
  for (const row of quoteLines.value) {
    const hit = (q.items || []).find((it: Dict) => it.line_id === row.line_id)
    if (hit) Object.assign(row, hit)
  }
}

async function saveQuote() {
  if (!quoteRef.value.supplier_id) { ElMessage.warning('请选择供应商'); return }
  const payload = { ...quoteRef.value, items: quoteLines.value }
  await saveRfqQuote(detail.value.id, quoteRef.value.supplier_id, payload)
  ElMessage.success('报价已保存')
  quoteVisible.value = false
  detail.value = await fetchRfqDetail(detail.value.id)
  cmp.value = await compareRfq(detail.value.id)
  await load()
}

// ---------------- 动作 ----------------
async function onPublish(row: Dict) {
  await publishRfq(row.id); ElMessage.success('已发布，可录入报价'); await load()
}
async function onClose(row: Dict) {
  await ElMessageBox.confirm('截止后仍可查看，但建议先录完报价。确认截止？', '截止询价单',
    { type: 'warning' })
  await closeRfq(row.id); ElMessage.success('已截止'); await load()
}
async function onDelete(row: Dict) {
  await ElMessageBox.confirm(`删除草稿 ${row.doc_no}？`, '删除询价单', { type: 'warning' })
  await deleteRfq(row.id); await load()
}
async function onExport() {
  // 走 axios 带 token 下载；直链 window.open 不带 token 会 401「未登录，请先登录」
  const params = {
    ...(query.value.status ? { status: query.value.status } : {}),
    ...(query.value.keyword ? { keyword: query.value.keyword } : {}),
  }
  await downloadBlobFile('/rfq/export.xlsx', params, '询价单.xlsx')
}

const lineTotal = (row: Dict) => Number(row.qty || 0)

// ---------------- 定标确认（CR-058） ----------------
const awardDlg = ref(false)
const awardRef = ref<Dict>({ supplier_id: null, reason: '', conclusion: '' })

function openAward() {
  awardRef.value = {
    supplier_id: detail.value.award_supplier_id || null,
    reason: detail.value.award_reason || '',
    conclusion: detail.value.award_conclusion || '',
  }
  awardDlg.value = true
}

async function saveAward() {
  if (!awardRef.value.supplier_id) { ElMessage.warning('请选择中选供应商'); return }
  const head = await awardRfq(detail.value.id, awardRef.value)
  detail.value = { ...detail.value, ...head }
  awardDlg.value = false
  ElMessage.success('已定标，可打印比价单')
}

// ---------------- 打印比价单（参考业务 Excel） ----------------
function quoteTotals(): Record<number, number> {
  const out: Record<number, number> = {}
  for (const row of cmp.value.rows || []) {
    for (const offer of row.offers || []) {
      out[offer.supplier_id] = (out[offer.supplier_id] || 0) + Number(offer.amount || 0)
    }
  }
  return out
}

async function printCompare() {
  let cfg: Dict = { title: '比 价 单', orientation: 'portrait',
    sections: { budget: true, conditions: true, scores: true, reason: true, conclusion: true },
    extra_rows: [], signatures: ['制表人', '部门负责人', '单位负责人', '日期'],
    signature_columns: 3, footer_note: '' }
  try { cfg = await fetchRfqPrintTemplate() } catch { /* 用默认模板 */ }
  const show = (k: string) => (cfg.sections || {})[k] !== false
  const qs = (detail.value.quotes || []) as Dict[]
  if (!qs.length) { ElMessage.warning('暂无报价，无法打印比价单'); return }
  const esc = (v: unknown) => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  const totals = quoteTotals()
  const amounts = qs.map((q: Dict) => Number(totals[q.supplier_id] || 0))
  const minAmount = Math.min(...amounts)
  const maxAmount = Math.max(...amounts)
  const budget = detail.value.budget_amount != null ? Number(detail.value.budget_amount) : null
  const awardedId = detail.value.award_supplier_id
  const money = (v: number) => fmtMoney(v)

  const sectionRow = (title: string) =>
    `<tr class="sec"><td colspan="${qs.length + 1}">${title}</td></tr>`

  const row = (label: string, fn: (q: Dict) => string, cls = '') =>
    `<tr class="${cls}"><th>${label}</th>` +
    qs.map((q: Dict) => `<td>${fn(q)}</td>`).join('') + '</tr>'

  const priceRow = row('报价（元）', (q) => {
    const amount = Number(totals[q.supplier_id] || 0)
    const isMin = amount === minAmount
    const isAward = awardedId === q.supplier_id
    const diff = amount - minAmount
    const diffPct = minAmount ? (diff / minAmount * 100) : 0
    return `<div class="price ${isMin ? 'is-low' : ''} ${isAward ? 'is-award' : ''}">${money(amount)}</div>` +
      (isMin ? '<span class="tag tag-low">最低价</span>'
        : `<div class="sub diff">+${money(diff)}（较最低 +${diffPct.toFixed(1)}%）</div>`) +
      (isAward ? '<span class="tag tag-award">中选</span>' : '')
  })

  const budgetRow = row('预算对比', (q) => {
    if (budget == null) return '<span class="muted">未填预算</span>'
    const amount = Number(totals[q.supplier_id] || 0)
    const diff = budget - amount
    if (diff >= 0) {
      return `<span class="ok">节余 ${money(diff)}</span>` +
        `<div class="sub">低于预算 ${(diff / budget * 100).toFixed(1)}%</div>`
    }
    return `<span class="over">超预算 ${money(-diff)}</span>` +
      `<div class="sub">超出 ${(amount / budget * 100 - 100).toFixed(1)}%</div>`
  })

  const scoreBar = (score: number | null | undefined, cls: string) => {
    if (score == null) return '<span class="muted">—</span>'
    const pct = Math.max(0, Math.min(100, Number(score) / 10 * 100))
    return `<div class="bar"><span style="width:${pct}%" class="${cls}"></span></div>` +
      `<span class="score">${Number(score).toFixed(2)}</span>`
  }

  const condRow = row('商务条件', (q) => `
    <div class="cond"><span>交期</span><b>${esc(q.delivery_period || '—')}</b></div>
    <div class="cond"><span>付款</span><b>${esc(q.payment_terms || '—')}</b></div>
    <div class="cond"><span>售后</span><b>${esc(q.after_sales || '—')}</b></div>
    <div class="cond"><span>联系</span><b>${esc([q.contact_name, q.contact_phone].filter(Boolean).join(' / ') || '—')}</b></div>
    ${q.remark ? `<div class="cond"><span>备注</span><b>${esc(q.remark)}</b></div>` : ''}`)

  const scoreRows = [
    sectionRow('综合评分（满分 10 分）'),
    row('价格评分', (q) => scoreBar(q.price_score, 'fill-price')),
    row('质量/技术评分', (q) => scoreBar(q.quality_score, 'fill-quality')),
    row('服务/货期评分', (q) => scoreBar(q.service_score, 'fill-service')),
    row('综合得分', (q) => `<div class="total-score ${awardedId === q.supplier_id ? 'win' : ''}">` +
      `${q.score_avg == null ? '—' : Number(q.score_avg).toFixed(2)}` +
      `<small> / 10</small></div>`),
  ].join('')

  const awardRow = row('比价结论', (q) => awardedId === q.supplier_id
    ? '<span class="check">✓ 中选</span>' : '<span class="muted">—</span>')
  const reasonRow = row('推荐理由', (q) => awardedId === q.supplier_id
    ? `<div class="reason">${esc(detail.value.award_reason || '')}</div>` : '<span class="muted">—</span>')

  const headCells = qs.map((q: Dict) => {
    const isAward = awardedId === q.supplier_id
    return `<th class="sup ${isAward ? 'win' : ''}">
      <div class="sup-name">${esc(q.supplier_name)}</div>
      <div class="sup-meta">${esc(q.channel || '报价')}${q.quote_date ? ' · ' + esc(q.quote_date) : ''}</div>
      ${isAward ? '<div class="ribbon">中选供应商</div>' : ''}
    </th>`
  }).join('')

  const extraHtml = ((cfg.extra_rows || []) as Dict[])
    .filter((r: Dict) => String(r.value || '').trim())
    .map((r: Dict) => `<tr><th>${esc(r.label)}</th><td colspan="${qs.length}">${esc(r.value)}</td></tr>`)
    .join('')
  const info = [
    ['项目名称', detail.value.title || ''],
    ['项目内容', detail.value.project || ''],
    ['责任部门', detail.value.responsibility_dept || ''],
    ['预算金额', budget == null ? '' : money(budget)],
    ['比价日期', (detail.value.deadline || detail.value.created_at || '').slice(0, 10)],
    ['比价人', detail.value.created_by_name || ''],
  ]

  const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>比价单 · ${esc(detail.value.title || detail.value.doc_no || '')}</title>
<style>
  @page { size: A4 ${cfg.orientation === 'portrait' ? 'portrait' : 'landscape'}; margin: 10mm 10mm 8mm; }
  * { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { margin: 0; color: #2B3440; font-family: "PingFang SC", "Microsoft YaHei", "SimSun", serif; font-size: 10.5px; line-height: 1.45; }
  .sheet { width: 100%; max-width: 19cm; margin: 0 auto; }
  /* 头部 */
  .hdr { display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 3px solid #0E4F4A; padding-bottom: 10px; }
  .brand { display: flex; gap: 12px; align-items: center; }
  .logo { width: 40px; height: 40px; border-radius: 9px; background: #0E4F4A; color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 18px; letter-spacing: 1px; }
  h1 { margin: 0; font-size: 20px; letter-spacing: 4px; color: #0B3B37; }
  .sub-title { margin-top: 2px; color: #5A6672; font-size: 11px; }
  .hdr-right { text-align: right; font-size: 10.5px; color: #5A6672; max-width: 360px; }
  .hdr-right b { color: #2B3440; }
  .docno { margin-top: 3px; font-family: Consolas, monospace; color: #0E4F4A; font-weight: 700; }

  /* 信息条 */
  .info { display: grid; grid-template-columns: repeat(3, 1fr); gap: 5px; margin: 9px 0 10px; }
  .cell { background: #F6F7F9; border: 1px solid #E4E7EC; border-left: 3px solid #0E4F4A; border-radius: 4px; padding: 6px 9px; }
  .cell span { display: block; color: #7C8794; font-size: 10px; letter-spacing: .5px; }
  .cell b { font-weight: 600; }
  .cell.hl { background: #FFFBEB; border-left-color: #F5D77A; }

  /* 对比表 */
  table { width: 100%; border-collapse: collapse; table-layout: fixed; }
  th, td { border: 1px solid #DDE1E6; padding: 5px 7px; vertical-align: top; }
  thead th { background: #F1F8F7; text-align: center; vertical-align: bottom; }
  thead th:first-child { width: 108px; background: #E4F2F0; text-align: left; color: #0E4F4A; }
  th.sup { position: relative; }
  .sup-name { font-size: 12.5px; font-weight: 700; color: #0B3B37; }
  .sup-meta { font-size: 10px; color: #7C8794; margin-top: 2px; }
  th.win { background: #E4F2F0; box-shadow: inset 0 -3px 0 #0E4F4A; }
  .ribbon { display: inline-block; margin-top: 5px; background: #0E4F4A; color: #fff; font-size: 10px; padding: 1px 8px; border-radius: 10px; }
  tbody th { width: 108px; background: #F8FAFA; text-align: left; font-weight: 600; color: #2B3440; }
  tr.sec td { background: #0E4F4A; color: #fff; font-weight: 600; letter-spacing: 1px; font-size: 11px; padding: 5px 9px; }
  td { text-align: left; font-size: 11px; }
  .price { font-family: Consolas, "JetBrains Mono", monospace; font-weight: 700; font-size: 14px; }
  .price.is-low { color: #8A5A00; }
  .price.is-award { text-decoration: underline; text-decoration-color: #0E4F4A; text-underline-offset: 3px; }
  .tag { display: inline-block; margin-top: 3px; font-size: 9.5px; padding: 0 6px; border-radius: 8px; }
  .tag-low { background: #FFFBEB; border: 1px solid #F5D77A; color: #8A5A00; }
  .tag-award { background: #0E4F4A; color: #fff; margin-left: 3px; }
  .ok { color: #0F7B4F; font-weight: 600; }
  .over { color: #B42318; font-weight: 600; }
  .sub { color: #7C8794; font-size: 10px; }
  .muted { color: #A6AFB9; }
  .cond { display: flex; gap: 6px; font-size: 10.5px; margin-bottom: 1px; }
  .cond span { color: #7C8794; min-width: 30px; }
  .cond b { font-weight: 500; }
  .bar { height: 6px; background: #EFF1F4; border-radius: 3px; overflow: hidden; margin-bottom: 2px; }
  .bar span { display: block; height: 100%; border-radius: 3px; }
  .fill-price { background: #1B5FA8; }
  .fill-quality { background: #0F7B4F; }
  .fill-service { background: #A8590B; }
  .score { font-family: Consolas, monospace; font-size: 10.5px; }
  .total-score { font-family: Consolas, monospace; font-weight: 700; font-size: 16px; color: #0E4F4A; }
  .total-score small { font-size: 9px; color: #7C8794; font-weight: 400; }
  .total-score.win { background: #E4F2F0; display: inline-block; padding: 0 8px; border-radius: 4px; }
  .check { color: #0E4F4A; font-weight: 700; font-size: 13px; }
  .reason { color: #2B3440; }

  /* 结论 */
  .conclusion { margin-top: 9px; border: 1px solid #CBD2DA; border-left: 4px solid #0E4F4A; background: #F1F8F7; border-radius: 4px; padding: 9px 12px; }
  .conclusion .k { font-weight: 700; color: #0E4F4A; margin-bottom: 3px; }
  /* 签字 */
  .sign { display: grid; grid-template-columns: repeat(${Math.min(4, Math.max(1, Number(cfg.signature_columns) || 3))}, 1fr); margin-top: 18px; gap: 10px 22px; }
  .sign .item { color: #5A6672; font-size: 11px; }
  .sign .line { border-bottom: 1px solid #A6AFB9; height: 30px; margin-top: 4px; }
  .foot { margin-top: 10px; display: flex; justify-content: space-between; color: #A6AFB9; font-size: 9.5px; border-top: 1px dashed #DDE1E6; padding-top: 6px; }
</style></head><body><div class="sheet">
  <div class="hdr">
    <div class="brand">
      <div class="logo">比</div>
      <div>
        <h1>${esc(cfg.title || '比 价 单')}</h1>
        <div class="sub-title">供应商比价与定标确认 · 采购内部资料</div>
      </div>
    </div>
    <div class="hdr-right">
      <div class="docno">${esc(detail.value.doc_no || '')}</div>
      <div>报价家数：<b>${qs.length}</b> 家 · 最低报价：<b>${money(minAmount)}</b></div>
      <div>最高报价：${money(maxAmount)} · 价差率：${minAmount ? ((maxAmount - minAmount) / minAmount * 100).toFixed(1) : '0.0'}%</div>
    </div>
  </div>

  <div class="info">
    ${info.map(([k, v], i) => `<div class="cell ${i === 3 ? 'hl' : ''}"><span>${k}</span><b>${esc(v)}</b></div>`).join('')}
    <div class="cell hl"><span>中选供应商</span><b>${esc(detail.value.award_supplier_name || '未定标')}</b></div>
    <div class="cell"><span>定标人 / 时间</span><b>${esc(detail.value.awarded_by_name || '—')}${detail.value.awarded_at ? ' · ' + esc(detail.value.awarded_at) : ''}</b></div>
  </div>

  <table>
    <thead><tr><th>比价项目</th>${headCells}</tr></thead>
    <tbody>
      ${sectionRow('一、报价对比')}
      ${priceRow}
      ${show('budget') ? budgetRow : ''}
      ${sectionRow('二、商务条件')}
      ${condRow}
      ${show('scores') ? scoreRows : ''}
      ${extraHtml}
      ${sectionRow('三、比价结论')}
      ${awardRow}
      ${show('reason') ? reasonRow : ''}
    </tbody>
  </table>

  <div class="conclusion">
    <div class="k">定标结论</div>
    <div>${esc(detail.value.award_conclusion || '（尚未填写定标结论）')}</div>
  </div>

  <div class="sign">
    ${(cfg.signatures || ['制表人', '部门负责人', '单位负责人', '日期']).map((label: string) =>
      `<div class="item"><span>${esc(label)}：${label.includes('制表') ? esc(detail.value.created_by_name || '') : ''}</span><div class="line"></div></div>`).join('')}
  </div>
  <div class="foot"><span>${esc(cfg.footer_note || '颜色说明：琥珀底=该行最低报价；深墨青=中选供应商；评分进度条按 10 分制换算')}</span>
  <span>CTMS · ${esc(detail.value.doc_no || '')}</span></div>
</div></body></html>`
  const w = window.open('', '_blank', 'width=1180,height=820')
  if (!w) { ElMessage.warning('浏览器拦截了打印窗口，请允许弹窗后重试'); return }
  w.document.write(html)
  w.document.close()
  w.focus()
  setTimeout(() => w.print(), 500)
}
onMounted(load)
</script>

<template>
  <div class="rfq-page">
    <el-card shadow="never">
      <div class="bar">
        <el-input v-model="query.keyword" placeholder="单号/标题/项目" clearable style="width: 220px"
                  @keyup.enter="() => { query.page = 1; load() }" />
        <el-select v-model="query.status" placeholder="全部状态" clearable style="width: 130px"
                   @change="() => { query.page = 1; load() }">
          <el-option v-for="s in statuses" :key="s.code" :label="s.label" :value="s.code" />
        </el-select>
        <el-button type="primary" @click="() => { query.page = 1; load() }">
          <el-icon><Search /></el-icon>查询
        </el-button>
        <span style="flex: 1"></span>
        <el-button @click="onExport"><el-icon><Download /></el-icon>导出 Excel</el-button>
        <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon>新建询价单</el-button>
      </div>
      <el-table v-loading="loading" :data="rows" border stripe size="small">
        <el-table-column prop="doc_no" label="单号" width="170" />
        <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
        <el-table-column prop="project" label="项目" min-width="140" show-overflow-tooltip />
        <el-table-column prop="deadline" label="截止时间" width="150" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="{ draft: 'info', open: 'success', closed: 'warning' }[row.status] || 'info'">
              {{ row.status_label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="line_count" label="行数" width="70" align="right" />
        <el-table-column prop="quote_count" label="报价家数" width="90" align="right" />
        <el-table-column prop="created_by_name" label="创建人" width="100" />
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">查看/比价</el-button>
            <el-button v-if="row.status === 'draft'" link @click="openEdit(row)">编辑</el-button>
            <el-button v-if="row.status === 'draft'" link @click="onPublish(row)">发布</el-button>
            <el-button v-if="row.status === 'open'" link @click="onClose(row)">截止</el-button>
            <el-button v-if="row.status === 'draft'" link type="danger" @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination class="pager" background layout="total, prev, pager, next, sizes"
                     :total="total" :current-page="query.page" :page-size="query.page_size"
                     :page-sizes="[20, 50, 100]"
                     @current-change="(p: number) => { query.page = p; load() }"
                     @size-change="(s: number) => { query.page_size = s; query.page = 1; load() }" />
    </el-card>

    <!-- 新建/编辑 -->
    <el-dialog v-model="formVisible" :title="editId ? '编辑询价单' : '新建询价单'" width="900px">
      <el-form label-width="90px">
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="标题" required>
            <el-input v-model="formRef.title" maxlength="128" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="项目">
            <el-input v-model="formRef.project" maxlength="128" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="截止时间">
            <el-date-picker v-model="formRef.deadline" type="datetime" value-format="YYYY-MM-DDTHH:mm"
                            style="width: 100%" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="备注">
            <el-input v-model="formRef.remark" maxlength="500" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="责任部门">
            <el-input v-model="formRef.responsibility_dept" maxlength="64" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="预算金额">
            <el-input-number v-model="formRef.budget_amount" :min="0" :precision="2"
                             :controls="false" style="width: 100%" /></el-form-item></el-col>
        </el-row>
      </el-form>
      <el-table :data="lines" border size="small">
        <el-table-column label="#" width="46">
          <template #default="{ $index }">{{ $index + 1 }}</template>
        </el-table-column>
        <el-table-column label="物料名称*" min-width="160">
          <template #default="{ row }"><el-input v-model="row.material_name" size="small" /></template>
        </el-table-column>
        <el-table-column label="规格" min-width="140">
          <template #default="{ row }"><el-input v-model="row.spec" size="small" /></template>
        </el-table-column>
        <el-table-column label="单位" width="90">
          <template #default="{ row }"><el-input v-model="row.unit" size="small" /></template>
        </el-table-column>
        <el-table-column label="数量" width="120">
          <template #default="{ row }">
            <el-input-number v-model="row.qty" :min="0" :controls="false" size="small" style="width: 100%" />
          </template>
        </el-table-column>
        <el-table-column label="需求日期" width="150">
          <template #default="{ row }">
            <el-date-picker v-model="row.need_date" type="date" value-format="YYYY-MM-DD"
                            size="small" style="width: 100%" />
          </template>
        </el-table-column>
        <el-table-column label="" width="60">
          <template #default="{ $index }">
            <el-button link type="danger" @click="delLine($index)">删</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-button class="mt8" size="small" @click="addLine">添加行</el-button>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" @click="saveForm">保存草稿</el-button>
      </template>
    </el-dialog>

    <!-- 详情 / 比价 -->
    <el-dialog v-model="detailVisible" :title="`${detail.doc_no} ${detail.title || ''}`" width="96%" top="4vh">
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="项目">{{ detail.project || '—' }}</el-descriptions-item>
        <el-descriptions-item label="截止">{{ detail.deadline || '—' }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ detail.status_label }}</el-descriptions-item>
        <el-descriptions-item label="报价家数">{{ (detail.quotes || []).length }}</el-descriptions-item>
      </el-descriptions>

      <div class="bar mt12">
        <el-button v-if="detail.status !== 'draft'" type="primary" plain @click="openQuote">
          <el-icon><DataAnalysis /></el-icon>录入/修改供应商报价
        </el-button>
        <el-button v-if="(detail.quotes || []).length" type="success" plain @click="openAward">
          比价确认（定标）
        </el-button>
        <el-button @click="printCompare">打印比价单</el-button>
        <el-tag v-if="detail.award_supplier_name" type="success">
          已定标：{{ detail.award_supplier_name }}
        </el-tag>
        <span style="flex: 1"></span>
        <span class="tip">最低价绿色高亮；差额 = 次低 − 最低</span>
      </div>

      <el-alert v-if="detail.status === 'closed' && conclusion" type="success" :closable="false"
                show-icon class="mt12"
                :title="`比价结束：${conclusion.count} 家报价，建议 ${conclusion.best.supplier_name}（合计 ${fmtMoney(conclusion.best.amount)}${conclusion.gap ? '，比次低省 ' + fmtMoney(conclusion.gap) : ''}）`" />

      <!-- 比价对比表（交叉表：行=物料，列=供应商；琥珀底=该行最低价） -->
      <div class="rfq-compare">
        <div class="rfq-compare__head">
          <b>比价对比表</b>
          <span class="rfq-compare__sub">
            共 {{ matrixRows.length }} 行 · {{ matrixSuppliers.length }} 家供应商 ·
            <span class="best-legend">琥珀底 = 该行最低价</span>
          </span>
          <span style="flex: 1"></span>
          <el-tag v-if="conclusion" type="success" effect="plain">
            建议：{{ conclusion.best.supplier_name }}（{{ fmtMoney(conclusion.best.amount) }}）
            <template v-if="conclusion.gap">，比次低省 {{ fmtMoney(conclusion.gap) }}</template>
          </el-tag>
        </div>
        <div class="rfq-compare__scroll">
          <table class="rfq-matrix">
            <thead>
              <tr>
                <th class="sticky-col">物料 / 需求</th>
                <th v-for="s in matrixSuppliers" :key="s.supplier_id" class="is-num">
                  <div class="sup-name">{{ s.supplier_name }}</div>
                  <div class="sup-meta">
                    {{ s.channel || '—' }}<template v-if="s.quote_date"> · {{ s.quote_date }}</template>
                  </div>
                  <div v-if="winCount[s.supplier_id]" class="win">最低价 ×{{ winCount[s.supplier_id] }}</div>
                </th>
                <th class="is-num">最低价</th>
                <th>最低价方</th>
                <th class="is-num">最高价</th>
                <th class="is-num">均价</th>
                <th class="is-num">价差率</th>
                <th class="is-num">报价家数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in matrixRows" :key="row.id">
                <td class="sticky-col">
                  <div class="mat-name">{{ row.material_name }}</div>
                  <div class="mat-meta">{{ row.spec || '—' }} · {{ fmtQty(row.qty) }} {{ row.unit || '' }}</div>
                </td>
                <td v-for="s in matrixSuppliers" :key="s.supplier_id" class="is-num"
                    :class="{ 'is-best': row.lowest && row.lowest.supplier_id === s.supplier_id }">
                  <template v-if="row.bySupplier[s.supplier_id]">
                    <div class="price">{{ fmtMoney(row.bySupplier[s.supplier_id].unit_price) }}</div>
                    <div class="cell-meta">
                      <template v-if="row.bySupplier[s.supplier_id].lead_days !== null">
                        交期 {{ row.bySupplier[s.supplier_id].lead_days }}天
                      </template>
                    </div>
                  </template>
                  <span v-else class="none">—</span>
                </td>
                <td class="is-num">{{ row.lowest ? fmtMoney(row.lowest.unit_price) : '—' }}</td>
                <td>{{ row.lowest ? row.lowest.supplier_name : '—' }}</td>
                <td class="is-num">{{ row.max === null ? '—' : fmtMoney(row.max) }}</td>
                <td class="is-num">{{ row.avg === null ? '—' : fmtMoney(row.avg) }}</td>
                <td class="is-num">{{ row.spread === null ? '—' : `${row.spread.toFixed(1)}%` }}</td>
                <td class="is-num">{{ row.count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <el-table :data="cmp.rows" border stripe size="small">
        <el-table-column type="expand">
          <template #default="{ row }">
            <el-table :data="row.offers" size="small" border>
              <el-table-column prop="supplier_name" label="供应商" min-width="160" />
              <el-table-column prop="unit_price" label="含税单价" width="110" align="right">
                <template #default="s">{{ fmtMoney(s.row.unit_price) }}</template>
              </el-table-column>
              <el-table-column prop="tax_rate" label="税率%" width="90" align="right" />
              <el-table-column prop="moq" label="MOQ" width="90" align="right" />
              <el-table-column prop="lead_days" label="交期(天)" width="90" align="right" />
              <el-table-column prop="amount" label="小计" width="120" align="right">
                <template #default="s">{{ fmtMoney(s.row.amount) }}</template>
              </el-table-column>
            </el-table>
          </template>
        </el-table-column>
        <el-table-column label="物料" min-width="180">
          <template #default="{ row }">{{ row.material_name }}（{{ row.spec || '—' }}）</template>
        </el-table-column>
        <el-table-column label="数量" width="90" align="right">
          <template #default="{ row }">{{ fmtQty(row.qty) }} {{ row.unit || '' }}</template>
        </el-table-column>
        <el-table-column label="最低价" width="190">
          <template #default="{ row }">
            <span v-if="row.lowest" class="low">
              {{ row.lowest.supplier_name }}：{{ fmtMoney(row.lowest.unit_price) }}
            </span>
            <span v-else class="tip">暂无报价</span>
          </template>
        </el-table-column>
        <el-table-column label="次低价" width="190">
          <template #default="{ row }">
            <span v-if="row.second">{{ row.second.supplier_name }}：{{ fmtMoney(row.second.unit_price) }}</span>
            <span v-else class="tip">—</span>
          </template>
        </el-table-column>
        <el-table-column label="差额" width="100" align="right">
          <template #default="{ row }">{{ row.diff === null ? '—' : fmtMoney(row.diff) }}</template>
        </el-table-column>
        <el-table-column label="差额率" width="100" align="right">
          <template #default="{ row }">
            {{ row.diff_pct === null ? '—' : `${row.diff_pct.toFixed(2)}%` }}
          </template>
        </el-table-column>
        <el-table-column label="报价家数" width="90" align="right">
          <template #default="{ row }">{{ row.offers.length }}</template>
        </el-table-column>
      </el-table>

      <div class="mt12">
        <el-divider content-position="left">供应商合计（按数量×最低报价之外的各自报价汇总）</el-divider>
        <el-table :data="cmp.supplier_totals" border size="small" style="width: 420px">
          <el-table-column prop="supplier_name" label="供应商" />
          <el-table-column label="合计金额" width="160" align="right">
            <template #default="{ row }">{{ fmtMoney(row.amount) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>

    <!-- 录入报价 -->
    <el-dialog v-model="quoteVisible" title="录入供应商报价" width="900px">
      <el-form label-width="90px">
        <el-row :gutter="12">
          <el-col :span="8"><el-form-item label="供应商" required>
            <el-select v-model="quoteRef.supplier_id" filterable style="width: 100%"
                       @change="onSupplierChange" @visible-change="ensureSuppliers">
              <el-option v-for="s in suppliers" :key="s.id" :label="s.name" :value="s.id" />
            </el-select></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="报价日期">
            <el-date-picker v-model="quoteRef.quote_date" type="date" value-format="YYYY-MM-DD"
                            style="width: 100%" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="渠道">
            <el-select v-model="quoteRef.channel" style="width: 100%">
              <el-option v-for="c in ['电话', '邮件', '微信', '到店', '其他']" :key="c" :label="c" :value="c" />
            </el-select></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="联系人">
            <el-input v-model="quoteRef.contact_name" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="电话">
            <el-input v-model="quoteRef.contact_phone" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="备注">
            <el-input v-model="quoteRef.remark" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="交货周期">
            <el-input v-model="quoteRef.delivery_period" placeholder="如 7-14 天" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="付款条件">
            <el-input v-model="quoteRef.payment_terms" placeholder="如 一次性支付" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="售后服务">
            <el-input v-model="quoteRef.after_sales" placeholder="如 优秀 / 1年换货" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="价格评分">
            <el-input-number v-model="quoteRef.price_score" :min="0" :max="10" :precision="2"
                             :controls="false" style="width: 100%" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="质量/技术评分">
            <el-input-number v-model="quoteRef.quality_score" :min="0" :max="10" :precision="2"
                             :controls="false" style="width: 100%" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="服务/货期评分">
            <el-input-number v-model="quoteRef.service_score" :min="0" :max="10" :precision="2"
                             :controls="false" style="width: 100%" />
            <span class="tip">综合得分=三项平均</span></el-form-item></el-col>
        </el-row>
      </el-form>
      <el-table :data="quoteLines" border size="small">
        <el-table-column label="物料" min-width="160">
          <template #default="{ row }">
            {{ (detail.lines || []).find((l: Dict) => l.id === row.line_id)?.material_name || row.line_id }}
          </template>
        </el-table-column>
        <el-table-column label="含税单价" width="140">
          <template #default="{ row }">
            <el-input-number v-model="row.unit_price" :min="0" :precision="2" :controls="false"
                             size="small" style="width: 100%" />
          </template>
        </el-table-column>
        <el-table-column label="税率%" width="110">
          <template #default="{ row }">
            <el-input-number v-model="row.tax_rate" :min="0" :max="100" :controls="false"
                             size="small" style="width: 100%" />
          </template>
        </el-table-column>
        <el-table-column label="MOQ" width="110">
          <template #default="{ row }">
            <el-input-number v-model="row.moq" :min="0" :controls="false" size="small" style="width: 100%" />
          </template>
        </el-table-column>
        <el-table-column label="交期(天)" width="110">
          <template #default="{ row }">
            <el-input-number v-model="row.lead_days" :min="0" :controls="false" size="small" style="width: 100%" />
          </template>
        </el-table-column>
        <el-table-column label="备注" min-width="140">
          <template #default="{ row }"><el-input v-model="row.remark" size="small" /></template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="quoteVisible = false">取消</el-button>
        <el-button type="primary" @click="saveQuote">保存报价</el-button>
      </template>
    </el-dialog>

    <!-- 比价确认（定标） -->
    <el-dialog v-model="awardDlg" title="比价确认（定标）" width="580px">
      <el-form label-width="110px">
        <el-form-item label="中选供应商" required>
          <el-select v-model="awardRef.supplier_id" filterable style="width: 100%"
                     placeholder="选择中选供应商">
            <el-option v-for="q in (detail.quotes || [])" :key="q.supplier_id"
                       :label="`${q.supplier_name}${q.score_avg != null ? '（综合 ' + q.score_avg.toFixed(2) + '）' : ''}`"
                       :value="q.supplier_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="推荐理由">
          <el-input v-model="awardRef.reason" type="textarea" :rows="2"
                    placeholder="如：价格在第二序列，但产品质量放心" />
        </el-form-item>
        <el-form-item label="比价结论">
          <el-input v-model="awardRef.conclusion" type="textarea" :rows="3"
                    placeholder="如：因进度要求较高，选择某供应商作为本次供货商" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="awardDlg = false">取消</el-button>
        <el-button type="primary" @click="saveAward">确认定标</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.bar { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.mt8 { margin-top: 8px; }
.mt12 { margin-top: 12px; }
.tip { color: var(--el-text-color-secondary); font-size: 12px; }
.low { color: var(--el-color-success); font-weight: 600; }
.pager { margin-top: 10px; justify-content: flex-end; }
/* CR-047：比价视觉参考 xunjia 设计系统（品牌深墨青 + 最低价琥珀） */
.rfq-compare { margin-top: 12px; }
.rfq-compare__head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap;
  color: var(--rfq-brand-800, #0E4F4A); }
.rfq-compare__sub { font-size: 12px; color: #5A6672; }
.best-legend { color: #8A5A00; background: #FFFBEB; border: 1px solid #F5D77A;
  padding: 1px 6px; border-radius: 3px; }
.rfq-compare__scroll { overflow: auto; max-height: 48vh; border: 1px solid #E4E7EC; border-radius: 4px; }
.rfq-matrix { border-collapse: separate; border-spacing: 0; width: max-content; min-width: 100%;
  font-size: 12px; }
.rfq-matrix th, .rfq-matrix td { padding: 7px 10px; border-bottom: 1px solid #EFF1F4;
  border-right: 1px solid #EFF1F4; vertical-align: top; background: #fff; }
.rfq-matrix thead th { position: sticky; top: 0; z-index: 2; background: #F1F8F7;
  color: #0E4F4A; font-weight: 600; text-align: left; }
.rfq-matrix thead th.is-num { text-align: right; }
.rfq-matrix .sticky-col { position: sticky; left: 0; z-index: 1; background: #fff;
  min-width: 180px; text-align: left; }
.rfq-matrix thead .sticky-col { z-index: 3; background: #E4F2F0; }
.rfq-matrix td.is-num { text-align: right; font-variant-numeric: tabular-nums; }
.rfq-matrix td.is-best { background: #FFFBEB; box-shadow: inset 3px 0 0 #F5D77A; }
.rfq-matrix td.is-best .price { color: #8A5A00; font-weight: 600; }
.rfq-matrix .price { font-weight: 600; }
.rfq-matrix .cell-meta, .rfq-matrix .mat-meta, .rfq-matrix .sup-meta { color: #7C8794; font-size: 11px; }
.rfq-matrix .sup-name { font-weight: 600; }
.rfq-matrix .win { color: #8A5A00; font-size: 11px; margin-top: 2px; }
.rfq-matrix .none { color: #A6AFB9; }
/* xunjia 设计令牌：品牌深墨青 + 最低价琥珀（仅本页作用域） */
.rfq-page {
  --rfq-brand-800: #0E4F4A;
  --el-color-primary: #0E4F4A;
  --el-color-primary-light-3: #1D8F84;
  --el-color-primary-light-5: #4FA89F;
  --el-color-primary-light-7: #A9D2CD;
  --el-color-primary-light-8: #CBE3E0;
  --el-color-primary-light-9: #F1F8F7;
  --el-color-primary-dark-2: #0B3B37;
}
</style>
