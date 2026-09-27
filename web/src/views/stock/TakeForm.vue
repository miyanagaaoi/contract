<script setup lang="ts">
/**
 * 盘点单表单与实盘录入（T-V2-28/30）。
 *
 * 流程：新建（盘点仓库 + 全盘/抽盘）→ 保存 → 生成行项（可按商品类型 / 指定物料筛选）
 * → 录入实盘数量（账面数量只读，差异行高亮）→ 保存实盘 → 提交 → 审核
 * （后端按差异自动生成盘盈入库 / 盘亏出库单并过账，页头回显生成单号）。
 *
 * 复用 `DocFormPage` 的表头 / 行项卡片 / 打印按钮，并通过具名插槽替换行项区为盘点录入表。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import ApproveDialog from '@/components/doc/ApproveDialog.vue'
import type { ApproveMode } from '@/components/doc/ApproveDialog.vue'
import DocFormPage from '@/components/doc/DocFormPage.vue'
import {
  docAction,
  fetchMasterOptions,
  generateTakeItems,
  saveTakeCounts,
  type Dict,
} from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { TakeCountInput } from '@/types/doc'

const API = '/api/stock/takes'
const TAKE_TYPES = [
  { label: '全盘', value: 'full' },
  { label: '抽盘', value: 'partial' },
]

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const formRef = ref<InstanceType<typeof DocFormPage> | null>(null)

const extra = ref<Dict>({
  warehouse_id: null,
  take_type: 'full',
  scope_note: '',
})

const docId = computed(() => (route.params.id ? Number(route.params.id) : null))
const canEdit = computed(() => auth.hasPerm('stock.take.edit'))
const canSubmit = computed(() => auth.hasPerm('stock.take.submit'))
const canApprove = computed(() => auth.hasPerm('stock.take.approve'))

const warehouses = ref<Dict[]>([])
async function ensureWarehouses() {
  if (warehouses.value.length) return
  try {
    warehouses.value = await fetchMasterOptions('warehouse')
  } catch {
    warehouses.value = []
  }
}
void ensureWarehouses()

/** 新建保存成功 → 转到编辑态以便生成行项（不跳回列表） */
async function onSaved(doc: { id: number }) {
  if (docId.value) return
  await router.replace({ name: 'stock-take-edit', params: { id: String(doc.id) } })
  await formRef.value?.load()
}

// ---------------- 数量展示 / 差异 ----------------
function decimalsOf(row: Record<string, any>): number {
  const d = row.uom_decimals
  return d === null || d === undefined ? 2 : Number(d)
}

function fmtQty(v: unknown, decimals = 2): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return n.toFixed(Math.max(0, Math.min(6, decimals)))
}

function bookOf(row: Record<string, any>): number {
  return Number(row.book_qty ?? 0)
}

function actualOf(row: Record<string, any>): number | null {
  const v = row.actual_qty
  return v === null || v === undefined || v === '' ? null : Number(v)
}

/** 差异 = 实盘 − 账面（实盘未填时回退到后端 diff_qty） */
function diffOf(row: Record<string, any>): number | null {
  const actual = actualOf(row)
  if (actual === null || Number.isNaN(actual)) {
    return row.diff_qty === null || row.diff_qty === undefined ? null : Number(row.diff_qty)
  }
  return Math.round((actual - bookOf(row)) * 1000) / 1000
}

function diffText(row: Record<string, any>): string {
  const d = diffOf(row)
  if (d === null) return '—'
  return `${d > 0 ? '+' : ''}${fmtQty(d, decimalsOf(row))}`
}

function diffClass(row: Record<string, any>): string {
  const d = diffOf(row)
  if (d === null || d === 0) return ''
  return d > 0 ? 'is-plus' : 'is-minus'
}

function diffRowClass({ row }: { row: Record<string, any> }): string {
  const d = diffOf(row)
  if (d === null || d === 0) return ''
  return d > 0 ? 'diff-plus-row' : 'diff-minus-row'
}

// ---------------- 生成行项 ----------------
const genVisible = ref(false)
const genLoading = ref(false)
const genTypeId = ref<number | null>(null)
const genProductIds = ref<number[]>([])
const productTypes = ref<Dict[]>([])
const products = ref<Dict[]>([])
const productLoading = ref(false)

async function openGenerate() {
  if (!docId.value) {
    ElMessage.warning('请先保存盘点单（表头）再生成行项')
    return
  }
  genTypeId.value = null
  genProductIds.value = []
  genVisible.value = true
  try {
    if (!productTypes.value.length) productTypes.value = await fetchMasterOptions('product-type')
  } catch {
    // 拦截器已提示
  }
  await searchProducts('')
}

async function searchProducts(keyword: string) {
  productLoading.value = true
  try {
    products.value = await fetchMasterOptions('product', keyword ? { keyword } : {})
  } catch {
    // 拦截器已提示
  } finally {
    productLoading.value = false
  }
}

/** 重新拉取详情（生成行项 / 保存实盘 / 审核后刷新） */
function reloadDoc() {
  return formRef.value?.load()
}

/** 生成行项：指定物料优先，其次商品类型；都不选则按全盘范围（有结存的全部物料） */
async function submitGenerate(reload?: () => void) {
  if (!docId.value) return
  const payload: Dict = {}
  if (genProductIds.value.length) payload.product_ids = genProductIds.value
  else if (genTypeId.value) payload.product_type_id = genTypeId.value
  genLoading.value = true
  try {
    const doc = await generateTakeItems(API, docId.value, payload)
    ElMessage.success(`已生成盘点行项，共 ${doc.items?.length ?? 0} 行（账面数量已固定）`)
    genVisible.value = false
    await reload?.()
  } catch {
    // 422（已审核/已作废等）由拦截器提示
  } finally {
    genLoading.value = false
  }
}

// ---------------- 实盘录入 ----------------
const counting = ref(false)

async function saveCounts(rows: Record<string, any>[], reload?: () => void) {
  if (!docId.value) return
  if (!rows.length) {
    ElMessage.warning('请先生成盘点行项')
    return
  }
  const counts: TakeCountInput[] = []
  for (let i = 0; i < rows.length; i += 1) {
    const actual = actualOf(rows[i])
    if (actual === null || Number.isNaN(actual)) {
      ElMessage.warning(`第 ${i + 1} 行：请填写实盘数量`)
      return
    }
    if (actual < 0) {
      ElMessage.warning(`第 ${i + 1} 行：实盘数量不能为负数`)
      return
    }
    if (decimalsOf(rows[i]) === 0 && actual !== Math.round(actual)) {
      ElMessage.warning(`第 ${i + 1} 行：单位不支持小数，实盘数量请填整数`)
      return
    }
    counts.push({ id: Number(rows[i].id), actual_qty: actual, diff_reason: rows[i].diff_reason || null })
  }
  counting.value = true
  try {
    const doc = await saveTakeCounts(API, docId.value, counts)
    const diffItems = (doc.items || []).filter((it) => Number(it.diff_qty || 0) !== 0).length
    ElMessage.success(diffItems ? `已保存实盘，其中 ${diffItems} 行存在差异` : '已保存实盘，账实一致')
    await reload?.()
  } catch {
    // 拦截器已提示
  } finally {
    counting.value = false
  }
}

// ---------------- 提交 / 审核 ----------------
const acting = ref(false)
const approveVisible = ref(false)
const approveMode = ref<ApproveMode>('approve')
const approveSubject = ref('盘点单')

async function doSubmit(reload?: () => void) {
  if (!docId.value) return
  acting.value = true
  try {
    await docAction(API, docId.value, 'submit')
    ElMessage.success('已提交审核')
    await reload?.()
  } catch {
    // 422（无行项 / 状态不符）由拦截器提示
  } finally {
    acting.value = false
  }
}

function openApprove(detail: Record<string, any>, mode: ApproveMode) {
  approveSubject.value = `盘点单 ${detail?.doc_no ?? ''}`
  approveMode.value = mode
  approveVisible.value = true
}

async function onApproveConfirm(payload: { mode: ApproveMode; reason: string }) {
  if (!docId.value) return
  acting.value = true
  try {
    await docAction(API, docId.value, payload.mode, payload.mode === 'approve' ? {} : { reason: payload.reason })
    ElMessage.success(payload.mode === 'approve' ? '已审核，盘盈/盘亏单已按差异生成' : '操作成功')
    approveVisible.value = false
    await formRef.value?.load()
  } catch {
    // 拦截器已提示
  } finally {
    acting.value = false
  }
}
</script>

<template>
  <div>
    <DocFormPage ref="formRef" v-model="extra" title="盘点单" kind-label="盘点单"
                 :api="API" perm-prefix="stock.take" list-route="stock-takes"
                 :require-items="false" :submit-items="false" :redirect-after-save="false"
                 :extra-required="[{ key: 'warehouse_id', label: '盘点仓库' }]"
                 @saved="onSaved">
      <template #header="{ detail }">
        <el-col :span="12">
          <el-form-item label="盘点仓库" required>
            <el-select v-model="extra.warehouse_id" filterable placeholder="请选择仓库"
                       style="width: 100%" @visible-change="ensureWarehouses">
              <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="盘点方式" required>
            <el-select v-model="extra.take_type" style="width: 100%">
              <el-option v-for="t in TAKE_TYPES" :key="t.value" :label="t.label" :value="t.value" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="盘盈入库单">
            <span class="gray">{{ detail?.generated_in_no || '—' }}</span>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="盘亏出库单">
            <span class="gray">{{ detail?.generated_out_no || '—' }}</span>
          </el-form-item>
        </el-col>
        <el-col :span="24">
          <el-form-item label="范围说明">
            <el-input v-model="extra.scope_note" type="textarea" :rows="2" maxlength="200"
                      show-word-limit placeholder="抽盘时说明抽样范围（如：仅盘 A 类物料）" />
          </el-form-item>
        </el-col>
      </template>

      <template #items-toolbar="{ detail, editable, reload, items }">
        <el-button v-if="editable && canEdit" type="primary" plain size="small" @click="openGenerate">
          <el-icon><Refresh /></el-icon>生成行项
        </el-button>
        <el-button v-if="editable && canEdit" size="small" :loading="counting"
                   @click="saveCounts(items, reload)">
          保存实盘数量
        </el-button>
        <span class="gray">共 {{ items.length }} 行；差异 = 实盘 − 账面</span>
      </template>

      <template #items="{ items, readonly }">
        <el-alert v-if="!items.length" type="info" :closable="false" show-icon class="mb"
                  title="还没有盘点行项：先点上方「保存草稿」建单，再点「生成行项」按全盘/抽盘范围拉取账面数量。" />
        <el-table :data="items" border stripe size="small" max-height="520" :row-class-name="diffRowClass">
          <el-table-column type="index" label="#" width="48" align="center" />
          <el-table-column label="物料" min-width="180">
            <template #default="{ row }">
              {{ row.product_name || '—' }}<span class="gray">（{{ row.product_code || '—' }}）</span>
            </template>
          </el-table-column>
          <el-table-column label="规格型号" min-width="110">
            <template #default="{ row }">{{ row.spec || '—' }}</template>
          </el-table-column>
          <el-table-column label="单位" width="70">
            <template #default="{ row }">{{ row.uom_name || '—' }}</template>
          </el-table-column>
          <el-table-column label="账面数量" width="110" align="right">
            <template #default="{ row }">{{ fmtQty(bookOf(row), decimalsOf(row)) }}</template>
          </el-table-column>
          <el-table-column label="实盘数量" width="140">
            <template #default="{ row }">
              <el-input-number v-if="!readonly" v-model="row.actual_qty" :min="0"
                               :precision="decimalsOf(row)" :controls="false" style="width: 100%" />
              <span v-else>{{ fmtQty(row.actual_qty, decimalsOf(row)) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="差异" width="100" align="right">
            <template #default="{ row }">
              <span :class="diffClass(row)">{{ diffText(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="差异原因" min-width="170">
            <template #default="{ row }">
              <el-input v-if="!readonly" v-model="row.diff_reason" placeholder="差异行建议填写" />
              <span v-else>{{ row.diff_reason || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="备注" min-width="120">
            <template #default="{ row }">{{ row.remark || '—' }}</template>
          </el-table-column>
          <template #empty>暂无盘点行项</template>
        </el-table>
        <div class="tips">
          账面数量在生成行项时冻结，只读；审核时系统按差异自动生成盘盈入库 / 盘亏出库单并过账。
        </div>
      </template>

      <template #actions="{ detail, reload }">
        <el-button v-if="detail && detail.status === 'draft' && canSubmit" type="success" plain
                   :loading="acting" @click="doSubmit(reload)">提交审核</el-button>
        <el-button v-if="detail && detail.status === 'submitted' && canApprove" type="primary"
                   :loading="acting" @click="openApprove(detail, 'approve')">审核</el-button>
        <el-button v-if="detail && (detail.status === 'approved' || detail.status === 'completed') && canApprove"
                   type="warning" plain :loading="acting"
                   @click="openApprove(detail, 'unapprove')">反审核</el-button>
      </template>
    </DocFormPage>

    <!-- 生成行项 -->
    <el-dialog v-model="genVisible" title="生成盘点行项" width="min(620px, 92vw)" append-to-body>
      <el-alert type="info" :closable="false" show-icon class="mb"
                title="账面数量取该仓库当前结存（生成时冻结）；实盘数量默认等于账面，随后在详情页修改。" />
      <el-form label-width="100px">
        <el-form-item label="商品类型">
          <el-select v-model="genTypeId" filterable clearable placeholder="按商品类型筛选（抽盘常用）"
                     style="width: 100%">
            <el-option v-for="t in productTypes" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="指定物料">
          <el-select v-model="genProductIds" multiple filterable remote clearable
                     :remote-method="searchProducts" :loading="productLoading"
                     placeholder="按物料筛选（可多选；留空则按商品类型/全盘）" style="width: 100%">
            <el-option v-for="p in products" :key="p.id" :label="`${p.name}（${p.code}）`" :value="p.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="tips">提示：重新生成会刷新已有行的账面数量（未审核前）。</div>
      <template #footer>
        <el-button @click="genVisible = false">取消</el-button>
        <el-button type="primary" :loading="genLoading" @click="submitGenerate(reloadDoc)">确认生成</el-button>
      </template>
    </el-dialog>

    <ApproveDialog v-model="approveVisible" :mode="approveMode" :loading="acting"
                   :subject="approveSubject" @confirm="onApproveConfirm" />
  </div>
</template>

<style scoped>
.mb { margin-bottom: var(--ctms-gap); }
.gray { color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); }
.tips { margin-top: 8px; color: var(--ctms-text-muted); font-size: var(--ctms-fs-xs); }
.is-plus { color: var(--ctms-success-text); font-weight: 600; }
.is-minus { color: var(--ctms-danger-text); font-weight: 600; }
:deep(.diff-plus-row td) { background: #f0f9eb !important; }
:deep(.diff-minus-row td) { background: #fef0f0 !important; }
</style>
