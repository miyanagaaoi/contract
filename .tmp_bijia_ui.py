import pathlib

# ---------- api ----------
p = pathlib.Path('web/src/api.ts')
t = p.read_text(encoding='utf-8')
if 'awardRfq' not in t:
    t = t.replace('''export async function compareRfq(id: number): Promise<Dict> {''',
'''export async function awardRfq(id: number, payload: Dict): Promise<Dict> {
  const { data } = await http.post(`/rfq/${id}/award`, payload)
  return data
}
export async function compareRfq(id: number): Promise<Dict> {''')
p.write_text(t, encoding='utf-8')

# ---------- RfqView ----------
p = pathlib.Path('web/src/views/purchase/RfqView.vue')
t = p.read_text(encoding='utf-8')

# imports
t = t.replace("  closeRfq, compareRfq, createRfq, deleteRfq, fetchMasterOptions, fetchRfqDetail,",
              "  awardRfq, closeRfq, compareRfq, createRfq, deleteRfq, fetchMasterOptions, fetchRfqDetail,")

# 头部表单：责任部门/预算
t = t.replace('''          <el-col :span="12"><el-form-item label="备注">
            <el-input v-model="formRef.remark" maxlength="500" /></el-form-item></el-col>''',
'''          <el-col :span="12"><el-form-item label="备注">
            <el-input v-model="formRef.remark" maxlength="500" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="责任部门">
            <el-input v-model="formRef.responsibility_dept" maxlength="64" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="预算金额">
            <el-input-number v-model="formRef.budget_amount" :min="0" :precision="2"
                             :controls="false" style="width: 100%" /></el-form-item></el-col>''')

# openCreate/openEdit 初始化
t = t.replace("formRef.value = { title: '', project: '', deadline: '', remark: '' }",
              "formRef.value = { title: '', project: '', deadline: '', remark: '',\n    responsibility_dept: '', budget_amount: null }")
t = t.replace('''  formRef.value = { title: detail.title, project: detail.project || '',
    deadline: (detail.deadline || '').replace(' ', 'T'), remark: detail.remark || '' }''',
'''  formRef.value = { title: detail.title, project: detail.project || '',
    deadline: (detail.deadline || '').replace(' ', 'T'), remark: detail.remark || '',
    responsibility_dept: detail.responsibility_dept || '',
    budget_amount: detail.budget_amount ?? null }''')

# 报价弹窗：交期/付款/售后与评分
t = t.replace('''          <el-col :span="8"><el-form-item label="备注">
            <el-input v-model="quoteRef.remark" /></el-form-item></el-col>''',
'''          <el-col :span="8"><el-form-item label="备注">
            <el-input v-model="quoteRef.remark" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="交货周期">
            <el-input v-model="quoteRef.delivery_period" placeholder="如 7-14 天" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="付款条件">
            <el-input v-model="quoteRef.payment_terms" placeholder="如 一次性支付" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="售后服务">
            <el-input v-model="quoteRef.after_sales" placeholder="如 优秀/1年换货" /></el-form-item></el-col>''')

t = t.replace('''const quoteRef = ref<Dict>({ supplier_id: null, quote_date: '', contact_name: '',
  contact_phone: '', channel: '微信', remark: '' })''',
'''const quoteRef = ref<Dict>({ supplier_id: null, quote_date: '', contact_name: '',
  contact_phone: '', channel: '微信', remark: '', delivery_period: '',
  payment_terms: '', after_sales: '' })''')
t = t.replace('''  quoteRef.value = { supplier_id: null, quote_date: new Date().toISOString().slice(0, 10),
    contact_name: '', contact_phone: '', channel: '微信', remark: '' }''',
'''  quoteRef.value = { supplier_id: null, quote_date: new Date().toISOString().slice(0, 10),
    contact_name: '', contact_phone: '', channel: '微信', remark: '',
    delivery_period: '', payment_terms: '', after_sales: '' }''')

# 报价行：评分列
t = t.replace('''        <el-table-column label="备注" min-width="140">
          <template #default="{ row }"><el-input v-model="row.remark" size="small" /></template>
        </el-table-column>''',
'''        <el-table-column label="价格评分" width="100">
          <template #default="{ row }">
            <el-input-number v-model="row.price_score" :min="0" :max="10" :controls="false"
                             size="small" style="width: 100%" />
          </template>
        </el-table-column>
        <el-table-column label="质量评分" width="100">
          <template #default="{ row }">
            <el-input-number v-model="row.quality_score" :min="0" :max="10" :controls="false"
                             size="small" style="width: 100%" />
          </template>
        </el-table-column>
        <el-table-column label="服务评分" width="100">
          <template #default="{ row }">
            <el-input-number v-model="row.service_score" :min="0" :max="10" :controls="false"
                             size="small" style="width: 100%" />
          </template>
        </el-table-column>
        <el-table-column label="备注" min-width="140">
          <template #default="{ row }"><el-input v-model="row.remark" size="small" /></template>
        </el-table-column>''')

# 详情工具栏按钮：定标 + 打印比价单
t = t.replace('''        <el-button v-if="detail.status !== 'draft'" type="primary" plain @click="openQuote">
          <el-icon><DataAnalysis /></el-icon>录入/修改供应商报价
        </el-button>''',
'''        <el-button v-if="detail.status !== 'draft'" type="primary" plain @click="openQuote">
          <el-icon><DataAnalysis /></el-icon>录入/修改供应商报价
        </el-button>
        <el-button v-if="(detail.quotes || []).length" type="success" plain @click="openAward">
          比价确认（定标）
        </el-button>
        <el-button @click="printCompare">打印比价单</el-button>
        <el-tag v-if="detail.award_supplier_name" type="success">
          已定标：{{ detail.award_supplier_name }}
        </el-tag>''')

# 脚本：定标 + 打印
t = t.replace('''onMounted(load)''',
'''// ---------------- 定标确认 ----------------
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

// ---------------- 打印比价单（参考业务 Excel 格式） ----------------
function quoteTotals(): Record<number, number> {
  const out: Record<number, number> = {}
  for (const row of cmp.value.rows || []) {
    for (const offer of row.offers || []) {
      out[offer.supplier_id] = (out[offer.supplier_id] || 0) + Number(offer.amount || 0)
    }
  }
  return out
}

function printCompare() {
  const qs = detail.value.quotes || []
  if (!qs.length) { ElMessage.warning('暂无报价，无法打印比价单'); return }
  const totals = quoteTotals()
  const head = [['项目名称', detail.value.title || ''], ['项目内容', detail.value.project || ''],
    ['责任部门', detail.value.responsibility_dept || ''], ['预算金额', detail.value.budget_amount != null ? fmtMoney(detail.value.budget_amount) : ''],
    ['比价日期', (detail.value.deadline || detail.value.created_at || '').slice(0, 10)], ['比价人', detail.value.created_by_name || '']]
  const rows: [string, (q: Dict) => string][] = [
    ['供应商名称', (q) => q.supplier_name || ''],
    ['联系人/电话', (q) => [q.contact_name, q.contact_phone].filter(Boolean).join(' / ')],
    ['报价（元）', (q) => fmtMoney(totals[q.supplier_id] || 0)],
    ['交货周期', (q) => q.delivery_period || ''],
    ['付款条件', (q) => q.payment_terms || ''],
    ['售后服务', (q) => q.after_sales || ''],
    ['备注', (q) => q.remark || ''],
    ['价格评分', (q) => q.price_score == null ? '' : String(q.price_score)],
    ['质量/技术评分', (q) => q.quality_score == null ? '' : String(q.quality_score)],
    ['服务/货期评分', (q) => q.service_score == null ? '' : String(q.service_score)],
    ['综合得分', (q) => q.score_avg == null ? '' : q.score_avg.toFixed(2)],
    ['比价结论', (q) => detail.value.award_supplier_id === q.supplier_id ? '√' : ''],
    ['推荐理由', (q) => detail.value.award_supplier_id === q.supplier_id ? (detail.value.award_reason || '') : ''],
  ]
  const info = head.map(([k, v]) => `<tr><th>${k}</th><td colspan="3">${v}</td></tr>`).join('')
  const supHead = `<tr><th style="width:140px">供应商</th>${qs.map((q: Dict) => `<th>${q.supplier_name}</th>`).join('')}</tr>`
  const body = rows.map(([label, fn]) => `<tr><th>${label}</th>${qs.map((q: Dict) => `<td>${fn(q)}</td>`).join('')}</tr>`).join('')
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>比价单</title>
  <style>@page{size:A4 landscape;margin:12mm}body{font-family:"SimSun","宋体",serif;font-size:12px}
  h1{text-align:center;font-size:20px;margin:0 0 12px}table{border-collapse:collapse;width:100%;table-layout:fixed}
  th,td{border:1px solid #333;padding:5px 6px;vertical-align:middle;word-break:break-all}
  tr>th:first-child{width:140px;background:#f2f2f2;text-align:left}thead th{background:#e8e8e8;text-align:center}
  .concl{margin-top:10px}.concl th{width:90px;background:#f2f2f2;text-align:left;vertical-align:top}
  .sign{display:flex;justify-content:space-between;margin-top:28px}</style></head><body>
  <h1>比 价 单</h1>
  <table>${info}</table>
  <table style="margin-top:10px"><thead>${supHead}</thead><tbody>${body}</tbody></table>
  <table class="concl"><tr><th>结论</th><td>${detail.value.award_conclusion || ''}</td></tr></table>
  <div class="sign"><span>制表人：${detail.value.created_by_name || ''}</span><span>部门负责人：</span>
  <span>单位负责人：</span></div></body></html>`
  const w = window.open('', '_blank', 'width=1100,height=760')
  if (!w) { ElMessage.warning('浏览器拦截了打印窗口'); return }
  w.document.write(html)
  w.document.close()
  w.focus()
  setTimeout(() => w.print(), 400)
}

onMounted(load)''')
p.write_text(t, encoding='utf-8')
print('RfqView bijia patched: awardDlg=', 'awardDlg' in t, 'print=', 'printCompare' in t)
