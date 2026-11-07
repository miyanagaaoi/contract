<script setup lang="ts">
/**
 * 询价报价（CR-044，部门内部版）：询价单 + 代录各家报价 + 比价报表。
 * 纯内部：不开放外部账号；不与采购流程联动。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DataAnalysis, Download, Plus, Search } from '@element-plus/icons-vue'

import {
  closeRfq, compareRfq, createRfq, deleteRfq, fetchMasterOptions, fetchRfqDetail,
  fetchRfqs, publishRfq, saveRfqQuote, updateRfq, type Dict,
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
const formRef = ref<Dict>({ title: '', project: '', deadline: '', remark: '' })
const lines = ref<Dict[]>([])
const editId = ref<number | null>(null)

function openCreate() {
  editId.value = null
  formRef.value = { title: '', project: '', deadline: '', remark: '' }
  lines.value = [{ material_name: '', spec: '', unit: '', qty: 1, need_date: '' }]
  formVisible.value = true
}

async function openEdit(row: Dict) {
  const detail = await fetchRfqDetail(row.id)
  editId.value = row.id
  formRef.value = { title: detail.title, project: detail.project || '',
    deadline: (detail.deadline || '').replace(' ', 'T'), remark: detail.remark || '' }
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
  contact_phone: '', channel: '微信', remark: '' })
const quoteLines = ref<Dict[]>([])

async function ensureSuppliers() {
  if (!suppliers.value.length) suppliers.value = await fetchMasterOptions('supplier')
}

function openQuote() {
  quoteRef.value = { supplier_id: null, quote_date: new Date().toISOString().slice(0, 10),
    contact_name: '', contact_phone: '', channel: '微信', remark: '' }
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
function onExport() {
  const qs = new URLSearchParams({ ...(query.value.status ? { status: query.value.status } : {}),
    ...(query.value.keyword ? { keyword: query.value.keyword } : {}) })
  window.open(`/api/rfq/export.xlsx?${qs.toString()}`, '_blank')
}

const lineTotal = (row: Dict) => Number(row.qty || 0)

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
