<script setup lang="ts">
/**
 * 单据行项编辑表格（V2.0，T-V2-24）。
 *
 * 能力：
 * - 物料远程下拉（`el-select` filterable + `fetchMasterOptions('product', { keyword })`），
 *   选中后带出**规格 / 单位 / 默认单价**快照，并按 `uom_decimals` 限制数量精度；
 * - 数量 × 单价 = 金额 联动（金额由后端最终按 `qty * unit_price` 计算，前端仅展示）；
 * - 只读快照列（下推进度：已下单 / 已入库 / 已出库；盘点：账面 / 实盘 / 差异）；
 * - 增删行、行合计；`readonly` 时全部降级为文本展示。
 */
import { computed, onMounted, reactive, ref } from 'vue'

import { fetchMasterOptions, type Dict } from '@/api'
import type { DocItem } from '@/types/doc'

type ExtraCol = 'ordered' | 'received' | 'shipped' | 'book' | 'actual' | 'diff'

const props = withDefaults(defineProps<{
  /** 行项数组（就地编辑，元素为普通对象或后端 DocItem） */
  items: Record<string, any>[]
  /** 只读模式（详情/已审核单据） */
  readonly?: boolean
  /** 是否显示行仓库列 */
  showWarehouse?: boolean
  /** 是否允许编辑单价（入库单下推时单价只读） */
  showPrice?: boolean
  /** 额外只读快照列 */
  extraCols?: ExtraCol[]
  /** 空行时提示 */
  emptyText?: string
}>(), {
  readonly: false,
  showWarehouse: false,
  showPrice: true,
  extraCols: () => [],
  emptyText: '暂无行项，请点击「添加行」',
})

const emit = defineEmits<{ change: [] }>()

const products = ref<Dict[]>([])
const loadingProducts = ref(false)
const warehouseOptions = ref<Dict[]>([])

const EXTRA_LABEL: Record<ExtraCol, string> = {
  ordered: '已下单', received: '已入库', shipped: '已出库',
  book: '账面数量', actual: '实盘数量', diff: '差异',
}

/** 行对象统一取唯一 key（新行无 id，用索引兜底） */
function rowKey(row: Record<string, any>, index: number): string {
  return String(row.id ?? `new-${index}`)
}

/** 数量精度：未取到单位时默认 2 位 */
function decimalsOf(row: Record<string, any>): number {
  const d = row.uom_decimals
  return d === null || d === undefined ? 2 : Number(d)
}

function qtyStep(row: Record<string, any>): number {
  return decimalsOf(row) === 0 ? 1 : 0.01
}

/** 展示数量（按单位小数位，保留 0 位时取整） */
function fmtQty(v: unknown, decimals = 2): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return n.toFixed(Math.max(0, Math.min(6, decimals)))
}

function fmtPrice(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  return Number.isNaN(n) ? String(v) : n.toFixed(2)
}

function fmtMoney(v: unknown): string {
  if (v === null || v === undefined || v === '') return '0.00'
  const n = Number(v)
  return Number.isNaN(n) ? String(v) : n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** 金额 = 数量 × 单价（四舍五入到分） */
function amountOf(row: Record<string, any>): number {
  const qty = Number(row.qty || 0)
  const price = Number(row.unit_price || 0)
  return Math.round(qty * price * 100) / 100
}

const totalAmount = computed(() => props.items.reduce((sum, r) => sum + amountOf(r), 0))

/** 单位不支持小数时给出即时提示 */
function integerHint(row: Record<string, any>): string {
  return decimalsOf(row) === 0 ? '该单位不支持小数，请填整数' : ''
}

/** 只读快照列的取值（下推进度 / 盘点差异） */
function extraValue(row: Record<string, any>, col: ExtraCol): number | null {
  const map: Record<ExtraCol, string> = {
    ordered: 'ordered_qty', received: 'received_qty', shipped: 'shipped_qty',
    book: 'book_qty', actual: 'actual_qty', diff: 'diff_qty',
  }
  const v = row[map[col]]
  return v === null || v === undefined ? null : Number(v)
}

async function loadProducts(keyword = '') {
  loadingProducts.value = true
  try {
    products.value = await fetchMasterOptions('product', keyword ? { keyword } : {})
  } catch {
    // 拦截器已提示
  } finally {
    loadingProducts.value = false
  }
}

function onProductSearch(keyword: string) {
  loadProducts(keyword)
}

/** 选中物料 → 带出规格 / 单位 / 默认单价快照 */
function onProductChange(row: Record<string, any>, productId: number | null) {
  const p = products.value.find((o) => o.id === productId)
  if (!p) {
    emit('change')
    return
  }
  row.product_code = p.code
  row.product_name = p.name
  row.spec = p.spec ?? null
  row.uom_name = p.uom_name ?? null
  row.uom_decimals = p.uom_decimals ?? null
  if (row.unit_price === null || row.unit_price === undefined || row.unit_price === 0) {
    row.unit_price = Number(p.default_price || 0)
  }
  emit('change')
}

/** 数量变化：整数单位下强制取整并提示 */
function onQtyChange(row: Record<string, any>, value: number | undefined) {
  if (decimalsOf(row) === 0 && value !== undefined && value !== null) {
    row.qty = Math.round(Number(value))
  } else {
    row.qty = value ?? 0
  }
  emit('change')
}

function addRow() {
  props.items.push({
    product_id: null,
    product_code: '',
    product_name: '',
    spec: null,
    uom_name: null,
    uom_decimals: null,
    qty: 1,
    unit_price: 0,
    warehouse_id: null,
    remark: '',
  })
  emit('change')
}

/** 合计行：序号→空，金额列→合计，其余为空 */
function summaryMethod({ columns }: { columns: { property?: string }[] }): string[] {
  return columns.map((_c, i) => {
    if (i === 0) return '合计'
    if (i === 6) return fmtMoney(totalAmount)
    return ''
  })
}

function removeRow(index: number) {
  props.items.splice(index, 1)
  emit('change')
}

onMounted(async () => {
  await loadProducts()
  if (props.showWarehouse) {
    try {
      warehouseOptions.value = await fetchMasterOptions('warehouse')
    } catch {
      warehouseOptions.value = []
    }
  }
})

defineExpose({ loadProducts, totalAmount })
</script>

<template>
  <div class="items">
    <el-table :data="items" border stripe size="small" show-summary :summary-method="summaryMethod">
      <el-table-column type="index" label="#" width="48" align="center" />
      <el-table-column label="物料" min-width="200">
        <template #default="{ row }">
          <el-select v-if="!readonly" v-model="row.product_id" filterable remote
                     :remote-method="onProductSearch" :loading="loadingProducts"
                     placeholder="输入编码/名称搜索" style="width: 100%"
                     @change="(v: number) => onProductChange(row, v)">
            <el-option v-for="p in products" :key="p.id"
                       :label="`${p.name}（${p.code}）`" :value="p.id" />
          </el-select>
          <span v-else>{{ row.product_name || '—' }}<span class="gray">（{{ row.product_code || '—' }}）</span></span>
        </template>
      </el-table-column>
      <el-table-column label="规格型号" min-width="120">
        <template #default="{ row }">{{ row.spec || '—' }}</template>
      </el-table-column>
      <el-table-column label="单位" width="80">
        <template #default="{ row }">{{ row.uom_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="数量" width="140">
        <template #default="{ row }">
          <el-input-number v-if="!readonly" :model-value="row.qty" :min="0"
                           :precision="decimalsOf(row)" :step="qtyStep(row)" :controls="false"
                           style="width: 100%" @update:model-value="(v: number | undefined) => onQtyChange(row, v)" />
          <span v-else>{{ fmtQty(row.qty, decimalsOf(row)) }}</span>
          <div v-if="!readonly && integerHint(row)" class="hint">{{ integerHint(row) }}</div>
        </template>
      </el-table-column>
      <el-table-column label="单价" width="130">
        <template #default="{ row }">
          <el-input-number v-if="!readonly && showPrice" v-model="row.unit_price" :min="0"
                           :precision="4" :controls="false" style="width: 100%" @change="emit('change')" />
          <span v-else>{{ fmtPrice(row.unit_price) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="金额" width="120" align="right">
        <template #default="{ row }">{{ fmtMoney(amountOf(row)) }}</template>
      </el-table-column>
      <el-table-column v-if="showWarehouse" label="仓库" width="150">
        <template #default="{ row }">
          <el-select v-if="!readonly" v-model="row.warehouse_id" filterable clearable
                     placeholder="默认按表头仓库" style="width: 100%" @change="emit('change')">
            <el-option v-for="w in warehouseOptions" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
          <span v-else>{{ row.warehouse_name || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column v-for="c in extraCols" :key="c" :label="EXTRA_LABEL[c]" width="100" align="right">
        <template #default="{ row }">{{ fmtQty(extraValue(row, c), decimalsOf(row)) }}</template>
      </el-table-column>
      <el-table-column label="备注" min-width="140">
        <template #default="{ row }">
          <el-input v-if="!readonly" v-model="row.remark" placeholder="可选" @change="emit('change')" />
          <span v-else>{{ row.remark || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column v-if="!readonly" label="操作" width="70" align="center" fixed="right">
        <template #default="{ $index }">
          <el-button link type="danger" size="small" @click="removeRow($index)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>{{ emptyText }}</template>
    </el-table>

    <div v-if="!readonly" class="actions">
      <el-button type="primary" plain size="small" @click="addRow">添加行</el-button>
      <span class="gray tips">数量精度按物料单位小数位限制；金额 = 数量 × 单价，由系统自动计算。</span>
    </div>
  </div>
</template>

<style scoped>
.actions { margin-top: 8px; display: flex; align-items: center; gap: 12px; }
.gray { color: #909399; }
.hint { color: #e6a23c; font-size: 12px; line-height: 1.4; }
.tips { font-size: 12px; }
</style>
