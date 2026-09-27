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

import QuickCreateDialog from '@/components/QuickCreateDialog.vue'
import { fetchMasterOptions, type Dict } from '@/api'
import type { DocItem } from '@/types/doc'
import { fmtMoney, fmtPrice, fmtQty } from '@/utils/format'

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
  /**
   * 是否显示金额相关列（单价 / 金额）。
   *
   * 与 `showPrice` 的区别：`showPrice=false` 的语义是「单价只读、但列仍要显示」
   * （入库单 / 出库单的单价沿用上游订单，需要核对金额）；而**调拨单根本不涉及金额**，
   * 需要整列隐藏。此前只有 `showPrice` 一个开关，于是 `TransferForm` 传了
   * `:show-price="false"` 却依然渲染单价与金额列 —— 与它自己的注释、以及
   * 07-stock.spec.ts 的预期都不符。
   */
  showAmount?: boolean
  /** 额外只读快照列 */
  extraCols?: ExtraCol[]
  /** 空行时提示 */
  emptyText?: string
  /** 校验失败的行索引（T3-6：行内错误定位，由 DocFormPage 传入） */
  errorRows?: number[]
}>(), {
  readonly: false,
  showWarehouse: false,
  showPrice: true,
  showAmount: true,
  extraCols: () => [],
  emptyText: '暂无行项，请点击「添加行」',
  errorRows: () => [],
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

/**
 * 校验失败行高亮（T3-6）。
 *
 * 刻意用 `row-class-name` 而不是新增列：行项表的单元格位置被 e2e 以
 * `td nth(1)/(4)` 依赖（helpers.ts:143、06-purchase.spec.ts:158），
 * 动列结构会直接打断测试。
 */
function rowClassName({ rowIndex }: { rowIndex: number }): string {
  return props.errorRows.includes(rowIndex) ? 'row-error' : ''
}

/** 数量精度：未取到单位时默认 2 位 */
function decimalsOf(row: Record<string, any>): number {
  const d = row.uom_decimals
  return d === null || d === undefined ? 2 : Number(d)
}

function qtyStep(row: Record<string, any>): number {
  return decimalsOf(row) === 0 ? 1 : 0.01
}

// fmtQty / fmtPrice / fmtMoney 统一走 @/utils/format（T1-3）。
// 关键修复：金额空值由 '0.00' 改为 '—'；非数值不再回退为 String(v)（避免渲染 "[object Object]"）。
// 注意：数量与单价保持**无千分位**（toFixed）——行项表列宽固定且需逐格核对，千分位会撑宽列。

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

// ---------------- V2.1 / N9：物料现场快建 ----------------
// 需求："物料选择框最右边增加小按钮，可以快速调用新增物料档案功能"。
// 放在本组件内实现（而非由各页面各自承载）：本组件已维护物料下拉缓存，
// 快建成功后可直接把新物料并入缓存并回填当前行，且**所有单据自动获得该能力**。
const quickRef = ref<InstanceType<typeof QuickCreateDialog> | null>(null)
let quickRow: Record<string, any> | null = null

function openQuickProduct(row: Record<string, any>) {
  quickRow = row
  quickRef.value?.open()
}

function onQuickProductCreated(item: Dict) {
  if (!item || !quickRow) return
  // 并入下拉缓存，避免该物料在本次会话中"搜不到"
  if (!products.value.some((p) => p.id === item.id)) products.value.push(item)
  quickRow.product_id = item.id
  quickRow.product_code = item.code ?? ''
  quickRow.product_name = item.name ?? ''
  if (!quickRow.spec) quickRow.spec = item.spec ?? null
  quickRow.uom_name = item.uom_name ?? quickRow.uom_name ?? null
  quickRow.uom_decimals = item.uom_decimals ?? quickRow.uom_decimals ?? null
  if (!Number(quickRow.unit_price)) quickRow.unit_price = Number(item.default_price || 0)
  quickRow = null
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

/** 合计行：序号→"合计"，金额列→合计，其余为空。
 *
 * 修复（V2.1 / AC-V2.1-03）：
 * 1. `totalAmount` 是 computed ref，**在 script 内必须写 `.value`**，否则传入 ref 对象会让
 *    `fmtMoney` 拿到非数值并渲染出 "[object Object]"；
 * 2. 金额列按 `prop` 标识定位，不再硬编码列索引 `i === 6`——列数会随
 *    `showWarehouse` / `extraCols` / `readonly` 变化，硬编码会错位。 */
function summaryMethod({ columns }: { columns: { property?: string }[] }): string[] {
  const amountIdx = columns.findIndex((c) => c.property === 'amount')
  return columns.map((_c, i) => {
    if (i === 0) return '合计'
    if (amountIdx >= 0 && i === amountIdx) return fmtMoney(totalAmount.value)
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
    <el-table :data="items" border stripe size="small" show-summary :summary-method="summaryMethod"
              :row-class-name="rowClassName">
      <el-table-column type="index" label="#" width="48" align="center" />
      <el-table-column label="物料" min-width="230">
        <template #default="{ row }">
          <div v-if="!readonly" class="product-pick">
            <el-select v-model="row.product_id" filterable remote
                       :remote-method="onProductSearch" :loading="loadingProducts"
                       placeholder="输入编码/名称搜索" style="flex: 1"
                       @change="(v: number) => onProductChange(row, v)">
              <el-option v-for="p in products" :key="p.id"
                         :label="`${p.name}（${p.code}）`" :value="p.id" />
            </el-select>
            <!-- V2.1（N9）：最右侧小按钮 → 弹窗新增物料并回填本行（不跳转，BR-V2.1-10） -->
            <el-button size="small" title="快速新增物料" @click="openQuickProduct(row)">＋</el-button>
          </div>
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
      <el-table-column v-if="showAmount" label="单价" width="130">
        <template #default="{ row }">
          <el-input-number v-if="!readonly && showPrice" v-model="row.unit_price" :min="0"
                           :precision="4" :controls="false" style="width: 100%" @change="emit('change')" />
          <span v-else>{{ fmtPrice(row.unit_price) }}</span>
        </template>
      </el-table-column>
      <el-table-column v-if="showAmount" label="金额" prop="amount" width="120" align="right">
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

    <!-- V2.1 / N9：物料快速新增（保存后回填当前行，不离开本单据） -->
    <QuickCreateDialog ref="quickRef" kind="product" @created="onQuickProductCreated" />
  </div>
</template>

<style scoped>
.product-pick { display: flex; align-items: center; gap: 4px; width: 100%; }
.actions { margin-top: 8px; display: flex; align-items: center; gap: 12px; }
.gray { color: var(--ctms-text-muted); }
.hint { color: var(--ctms-warning-text); font-size: var(--ctms-fs-xs); line-height: 1.4; }
.tips { font-size: var(--ctms-fs-xs); }
/* 校验失败行（T3-6）：与 DocFormPage 顶部的行错误提示条呼应，便于快速定位 */
:deep(.el-table__row.row-error) td {
  background-color: #fef0f0;
}
</style>
