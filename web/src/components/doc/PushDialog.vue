<script setup lang="ts">
/**
 * 单据下推弹窗（V2.0）：采购/销售申请单 → 订单 / 采购单 → 入库单 / 销售订单 → 出库单。
 *
 * - 默认全选并按**剩余可下推量**（`qty - 已下推量`）预填，可勾行、改量；
 * - 申请单下推需选**往来单位**（采购选供应商、销售选客户，后端强制），订单下推需选**仓库**；
 * - 单价：申请 → 订单可改（后端支持 `unit_price`）；订单 → 出入库单沿用订单单价（只读）；
 * - 下推成功后返回新建的下游单据，由父页面提示并跳转。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { fetchDoc, fetchMasterOptions, pushDoc, type Dict } from '@/api'
import type { DocItem, DocRecord, PushRow } from '@/types/doc'
import { todayLocal } from '@/utils/format'

const props = withDefaults(defineProps<{
  /** 源单据接口前缀 */
  api: string
  /** 下推目标：order=上下游订单，stock=出入库单 */
  destType: 'order' | 'stock'
  /** 生成的下游单据名称（提示语用） */
  destLabel: string
  /** 往来单位类型：采购=supplier，销售=customer */
  partyKind?: 'supplier' | 'customer'
  /** 剩余量取值字段（申请→订单用 ordered_qty，订单→入库 received_qty，订单→出库 shipped_qty） */
  usedField?: 'ordered_qty' | 'received_qty' | 'shipped_qty'
  /** 出入库单类型字段（in_type / out_type） */
  stockTypeField?: 'in_type' | 'out_type'
  /** 出入库单类型可选项 */
  stockTypeOptions?: string[]
  /** 仓库选择项的提示语（入库仓库 / 出库仓库） */
  warehouseLabel?: string
}>(), {
  partyKind: 'supplier',
  usedField: undefined,
  stockTypeField: 'in_type',
  stockTypeOptions: () => ['采购入库', '退货入库', '其他入库'],
  warehouseLabel: '',
})

const emit = defineEmits<{ done: [doc: DocRecord] }>()

const visible = ref(false)
const loading = ref(false)
const source = ref<DocRecord | null>(null)
const rows = ref<Record<string, any>[]>([])
const selected = ref<Record<string, any>[]>([])
const partyId = ref<number | null>(null)
const warehouseId = ref<number | null>(null)
const stockType = ref('')
const docDate = ref(todayLocal())
const tableRef = ref()

const parties = ref<Dict[]>([])
const warehouses = ref<Dict[]>([])

/** 已下推数量字段：申请→订单看 ordered_qty，订单→入库看 received_qty，订单→出库看 shipped_qty */
const usedField = computed<keyof DocItem>(() => {
  if (props.usedField) return props.usedField as keyof DocItem
  return props.destType === 'order' ? 'ordered_qty' : 'received_qty'
})

const usedLabel = computed(() => {
  if (usedField.value === 'ordered_qty') return '已下单'
  if (usedField.value === 'received_qty') return '已入库'
  return '已出库'
})

const partyLabel = computed(() => (props.partyKind === 'customer' ? '客户' : '供应商'))
const stockTypeLabel = computed(() => (props.stockTypeField === 'out_type' ? '出库类型' : '入库类型'))
const warehouseLabel = computed(() => props.warehouseLabel
  || (props.stockTypeField === 'out_type' ? '出库仓库' : '入库仓库'))

function usedQty(row: Record<string, any>): number {
  return Number(row[usedField.value] || 0)
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
      parties.value = await fetchMasterOptions(props.partyKind === 'customer' ? 'customer' : 'supplier')
    } else {
      warehouses.value = await fetchMasterOptions('warehouse')
    }
  } catch {
    // 拦截器已提示
  }
}

/** 打开弹窗：先拉最新详情（行项 id 会随编辑变化），再默认勾选剩余量 > 0 的行 */
async function open(doc: DocRecord) {
  source.value = doc
  docDate.value = todayLocal()
  partyId.value = (props.partyKind === 'customer'
    ? doc.customer_id
    : (doc.suggest_supplier_id ?? doc.supplier_id)) ?? null
  warehouseId.value = (doc.ship_warehouse_id ?? doc.receipt_warehouse_id) ?? null
  stockType.value = props.stockTypeOptions[0] || ''
  loading.value = true
  visible.value = true
  try {
    // 列表行不含行项，且行项 id 可能在编辑后变化，必须按详情取最新数据
    const fresh = await fetchDoc(props.api, doc.id)
    source.value = fresh
    partyId.value = (props.partyKind === 'customer'
      ? fresh.customer_id
      : (fresh.suggest_supplier_id ?? fresh.supplier_id ?? partyId.value)) ?? partyId.value
    warehouseId.value = (fresh.ship_warehouse_id ?? fresh.receipt_warehouse_id ?? warehouseId.value) ?? null
    buildRows(fresh)
    await loadOptions()
    setTimeout(() => {
      for (const row of rows.value) {
        if (row.push_qty > 0) tableRef.value?.toggleRowSelection(row, true)
      }
    }, 0)
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function buildRows(doc: DocRecord) {
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
    shipped_qty: it.shipped_qty,
    unit_price: it.unit_price,
    push_qty: Math.max(0, Math.round((Number(it.qty || 0)
      - Number((usedField.value === 'ordered_qty' ? it.ordered_qty
        : usedField.value === 'received_qty' ? it.received_qty : it.shipped_qty) || 0)) * 1000) / 1000),
  }))
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
  if (props.destType === 'order' && !partyId.value) {
    ElMessage.warning(`请选择${partyLabel.value}`)
    return
  }
  if (props.destType === 'stock' && !warehouseId.value) {
    ElMessage.warning(`请选择${warehouseLabel.value}`)
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
  if (props.destType === 'order') {
    // 销售申请下推销售订单按后端契约传 customer_id；采购申请下推采购单传 supplier_id
    payload[props.partyKind === 'customer' ? 'customer_id' : 'supplier_id'] = partyId.value
  } else {
    payload.warehouse_id = warehouseId.value
    payload[props.stockTypeField] = stockType.value
  }

  loading.value = true
  try {
    const doc = await pushDoc(props.api, source.value!.id, payload)
    ElMessage.success(`已生成${props.destLabel} ${doc.doc_no}`)
    visible.value = false
    emit('done', doc)
  } catch {
    // 422（超量 / 缺往来单位 / 缺仓库）由拦截器提示
  } finally {
    loading.value = false
  }
}

defineExpose({ open })
</script>

<template>
  <el-dialog v-model="visible" :title="`下推生成${destLabel}`" width="min(860px, 92vw)" append-to-body>
    <el-alert type="info" :closable="false" show-icon class="mb"
              :title="`来源单据：${source?.doc_no ?? ''}；默认按剩余量全推，可勾选行并调整数量。`" />
    <el-form inline>
      <el-form-item label="单据日期">
        <el-date-picker v-model="docDate" type="date" value-format="YYYY-MM-DD" style="width: 160px" />
      </el-form-item>
      <el-form-item v-if="destType === 'order'" :label="partyLabel" required>
        <el-select v-model="partyId" filterable :placeholder="`请选择${partyLabel}`" style="width: 200px">
          <el-option v-for="s in parties" :key="s.id" :label="`${s.name}（${s.code}）`" :value="s.id" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="destType === 'stock'" :label="warehouseLabel" required>
        <el-select v-model="warehouseId" filterable :placeholder="`请选择仓库`" style="width: 180px">
          <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="destType === 'stock'" :label="stockTypeLabel">
        <el-select v-model="stockType" style="width: 130px">
          <el-option v-for="t in stockTypeOptions" :key="t" :label="t" :value="t" />
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
      <el-table-column :label="usedLabel" width="90" align="right">
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
.mb { margin-bottom: var(--ctms-gap); }
.gray { color: var(--ctms-text-muted); }
</style>
