<script setup lang="ts">
/**
 * 单据下推弹窗（V2.0）：采购申请单 → 采购单 / 采购单 → 入库单。
 *
 * - 默认全选并按**剩余可下推量**（`qty - ordered_qty` / `qty - received_qty`）预填，可勾行、改量；
 * - 采购申请单下推需选**供应商**（后端强制），入库单下推需选**仓库**；
 * - 单价：申请 → 采购单可改（后端支持 `unit_price`）；采购单 → 入库单沿用采购单价（只读）。
 * - 下推成功后返回新建的下游单据，由父页面提示并跳转。
 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import { fetchMasterOptions, pushDoc, type Dict } from '@/api'
import type { DocItem, DocRecord, PushRow } from '@/types/doc'

const props = withDefaults(defineProps<{
  /** 源单据接口前缀 */
  api: string
  /** 下推目标：order=采购单，stock=入库单 */
  destType: 'order' | 'stock'
  /** 生成的下游单据名称（提示语用） */
  destLabel: string
}>(), {})

const emit = defineEmits<{ done: [doc: DocRecord] }>()

const visible = ref(false)
const loading = ref(false)
const source = ref<DocRecord | null>(null)
const rows = ref<Record<string, any>[]>([])
const selected = ref<Record<string, any>[]>([])
const supplierId = ref<number | null>(null)
const warehouseId = ref<number | null>(null)
const inType = ref('采购入库')
const docDate = ref(new Date().toISOString().slice(0, 10))
const tableRef = ref()

const suppliers = ref<Dict[]>([])
const warehouses = ref<Dict[]>([])
const IN_TYPES = ['采购入库', '退货入库', '其他入库']

/** 已下推数量：申请→采购单看 ordered_qty，采购单→入库单看 received_qty */
function usedQty(row: Record<string, any>): number {
  const field = props.destType === 'order' ? 'ordered_qty' : 'received_qty'
  return Number(row[field] || 0)
}

/** 已下推列标题 */
function usedLabel(): string {
  return props.destType === 'order' ? '已下单' : '已入库'
}

function fmtQty(v: unknown, decimals = 2): string {
  const n = Number(v ?? 0)
  return n.toFixed(Math.max(0, Math.min(6, decimals)))
}

function balanceOf(row: Record<string, any>): number {
  return Math.max(0, Math.round((Number(row.qty || 0) - usedQty(row)) * 1000) / 1000)
}

function decimalsOf(row: Record<string, any>): number {
  return row.uom_decimals === null || row.uom_decimals === undefined ? 2 : Number(row.uom_decimals)
}

async function loadOptions() {
  try {
    if (props.destType === 'order') {
      suppliers.value = await fetchMasterOptions('supplier')
    } else {
      warehouses.value = await fetchMasterOptions('warehouse')
    }
  } catch {
    // 拦截器已提示
  }
}

/** 打开弹窗：默认全选剩余量 > 0 的行 */
async function open(doc: DocRecord) {
  source.value = doc
  docDate.value = new Date().toISOString().slice(0, 10)
  supplierId.value = doc.suggest_supplier_id ?? doc.supplier_id ?? null
  warehouseId.value = doc.receipt_warehouse_id ?? null
  rows.value = (doc.items || []).map((it: DocItem) => ({
    src_item_id: it.id,
    product_name: it.product_name,
    product_code: it.product_code,
    spec: it.spec,
    uom_name: it.uom_name,
    uom_decimals: it.uom_decimals,
    qty: it.qty,
    ordered_qty: it.ordered_qty,
    received_qty: it.received_qty,
    unit_price: it.unit_price,
    push_qty: balanceOf(it as unknown as Record<string, any>),
  }))
  visible.value = true
  await loadOptions()
  // 默认全选剩余可推行
  setTimeout(() => {
    for (const row of rows.value) {
      if (row.push_qty > 0) tableRef.value?.toggleRowSelection(row, true)
    }
  }, 0)
}

async function submit() {
  const picked = selected.value.filter((r) => Number(r.push_qty) > 0)
  if (!picked.length) {
    ElMessage.warning('请至少勾选一行并填写下推数量')
    return
  }
  for (const row of picked) {
    const balance = balanceOf(row)
    if (Number(row.push_qty) > balance) {
      ElMessage.warning(`「${row.product_name}」下推数量超过剩余可下推量 ${fmtQty(balance, decimalsOf(row))}`)
      return
    }
    if (decimalsOf(row) === 0 && Number(row.push_qty) !== Math.round(Number(row.push_qty))) {
      ElMessage.warning(`「${row.product_name}」单位不支持小数，数量请填整数`)
      return
    }
  }
  if (props.destType === 'order' && !supplierId.value) {
    ElMessage.warning('请选择供应商')
    return
  }
  if (props.destType === 'stock' && !warehouseId.value) {
    ElMessage.warning('请选择入库仓库')
    return
  }

  const payload: Dict = {
    doc_date: docDate.value,
    items: picked.map<PushRow>((r) => ({
      src_item_id: r.src_item_id,
      qty: Number(r.push_qty),
      ...(props.destType === 'order' ? { unit_price: Number(r.unit_price || 0) } : {}),
    })),
  }
  if (props.destType === 'order') payload.supplier_id = supplierId.value
  else {
    payload.warehouse_id = warehouseId.value
    payload.in_type = inType.value
  }

  loading.value = true
  try {
    const doc = await pushDoc(props.api, source.value!.id, payload)
    ElMessage.success(`已生成${props.destLabel} ${doc.doc_no}`)
    visible.value = false
    emit('done', doc)
  } catch {
    // 422（超量 / 缺供应商）由拦截器提示
  } finally {
    loading.value = false
  }
}

defineExpose({ open })
</script>

<template>
  <el-dialog v-model="visible" :title="`下推生成${destLabel}`" width="860px" append-to-body>
    <el-alert type="info" :closable="false" show-icon class="mb"
              :title="`来源单据：${source?.doc_no ?? ''}；默认按剩余量全推，可勾选行并调整数量。`" />
    <el-form inline>
      <el-form-item label="单据日期">
        <el-date-picker v-model="docDate" type="date" value-format="YYYY-MM-DD" style="width: 160px" />
      </el-form-item>
      <el-form-item v-if="destType === 'order'" label="供应商" required>
        <el-select v-model="supplierId" filterable placeholder="请选择供应商" style="width: 200px">
          <el-option v-for="s in suppliers" :key="s.id" :label="`${s.name}（${s.code}）`" :value="s.id" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="destType === 'stock'" label="入库仓库" required>
        <el-select v-model="warehouseId" filterable placeholder="请选择仓库" style="width: 180px">
          <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="destType === 'stock'" label="入库类型">
        <el-select v-model="inType" style="width: 130px">
          <el-option v-for="t in IN_TYPES" :key="t" :label="t" :value="t" />
        </el-select>
      </el-form-item>
    </el-form>

    <el-table ref="tableRef" :data="rows" border stripe size="small" max-height="360"
              @selection-change="(v: Record<string, any>[]) => (selected = v)">
      <el-table-column type="selection" width="46" :selectable="(r: Record<string, any>) => balanceOf(r) > 0" />
      <el-table-column label="物料" min-width="180">
        <template #default="{ row }">
          {{ row.product_name }}<span class="gray">（{{ row.product_code }}）</span>
        </template>
      </el-table-column>
      <el-table-column label="规格" min-width="110">
        <template #default="{ row }">{{ row.spec || '—' }}</template>
      </el-table-column>
      <el-table-column label="单位" width="70">
        <template #default="{ row }">{{ row.uom_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="单据数量" width="96" align="right">
        <template #default="{ row }">{{ fmtQty(row.qty, decimalsOf(row)) }}</template>
      </el-table-column>
      <el-table-column :label="usedLabel()" width="90" align="right">
        <template #default="{ row }">{{ fmtQty(usedQty(row), decimalsOf(row)) }}</template>
      </el-table-column>
      <el-table-column label="剩余可推" width="96" align="right">
        <template #default="{ row }">{{ fmtQty(balanceOf(row), decimalsOf(row)) }}</template>
      </el-table-column>
      <el-table-column label="本次下推" width="130">
        <template #default="{ row }">
          <el-input-number v-model="row.push_qty" :min="0" :max="balanceOf(row)"
                           :precision="decimalsOf(row)" :controls="false" style="width: 100%" />
        </template>
      </el-table-column>
      <el-table-column label="单价" width="120">
        <template #default="{ row }">
          <el-input-number v-if="destType === 'order'" v-model="row.unit_price" :min="0"
                           :precision="4" :controls="false" style="width: 100%" />
          <span v-else>{{ fmtQty(row.unit_price, 2) }}</span>
        </template>
      </el-table-column>
      <template #empty>没有可下推的行项</template>
    </el-table>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="loading" @click="submit">确认下推</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.mb { margin-bottom: 12px; }
.gray { color: #909399; }
</style>
