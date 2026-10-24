<script setup lang="ts">
/**
 * 出库单「更多 → 退库」弹窗（V2.6.1 / CR-022）。
 *
 * 数据源：`GET /out-orders/{id}/return-preview` 返回每行 已出/已退/可退；
 * 交互：勾选行 + 填退库数量（默认=可退，可改小），提交后生成一张**草稿**入库单
 *（类型=退库入库，来源指向原出库单），不在此处直接过账——沿用"入库单审核即过账"。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { createStockReturn, fetchStockReturnPreview, type Dict } from '@/api'
import { fmtQty } from '@/utils/format'

const props = defineProps<{ modelValue: boolean; doc: Dict | null }>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'done', newDoc: Dict): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const loading = ref(false)
const submitting = ref(false)
const info = ref<Dict>({})
const rows = ref<Dict[]>([])
const remark = ref('')
const docDate = ref('')

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

async function load() {
  if (!props.doc) return
  loading.value = true
  try {
    const data = await fetchStockReturnPreview(Number(props.doc.id))
    info.value = data
    docDate.value = today()
    remark.value = `由出库单 ${data.doc_no} 退库`
    rows.value = (data.rows || []).map((r: Dict) => ({
      ...r,
      checked: Number(r.returnable_qty) > 0,
      return_qty: Number(r.returnable_qty),
    }))
  } catch {
    rows.value = []
  } finally {
    loading.value = false
  }
}

watch(visible, (open) => { if (open) load() })

const selectedRows = computed(() => rows.value.filter((r) => r.checked && Number(r.return_qty) > 0))
const totalQty = computed(() => selectedRows.value.reduce((s, r) => s + Number(r.return_qty || 0), 0))

function toggleAll(v: boolean) {
  for (const r of rows.value) {
    if (Number(r.returnable_qty) > 0) r.checked = v
  }
}

function clampQty(row: Dict) {
  const max = Number(row.returnable_qty)
  let v = Number(row.return_qty || 0)
  if (!Number.isFinite(v) || v < 0) v = 0
  if (v > max) {
    v = max
    ElMessage.warning(`${row.product_name}：退库数量不能超过可退数量 ${fmtQty(max)}`)
  }
  row.return_qty = v
}

function decimalsOf(row: Dict): number {
  const d = row.uom_decimals
  return d === null || d === undefined ? 2 : Number(d)
}

async function submit() {
  if (!props.doc) return
  if (!selectedRows.value.length) {
    ElMessage.warning('请至少勾选一行并填写退库数量')
    return
  }
  const bad = selectedRows.value.find((r) => Number(r.return_qty) <= 0
    || Number(r.return_qty) > Number(r.returnable_qty))
  if (bad) {
    ElMessage.warning(`${bad.product_name} 的退库数量不合法（须大于 0 且不超过可退数量）`)
    return
  }
  submitting.value = true
  try {
    const created = await createStockReturn(Number(props.doc.id), {
      doc_date: docDate.value || undefined,
      remark: remark.value || undefined,
      rows: selectedRows.value.map((r) => ({
        item_id: Number(r.item_id),
        qty: Number(r.return_qty),
      })),
    })
    ElMessage.success(`已生成退库入库单 ${created.doc_no}（草稿，审核后过账）`)
    visible.value = false
    emit('done', created as Dict)
  } catch {
    // 拦截器已提示
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" title="退库（生成退库入库单）" width="880px"
             :close-on-click-modal="false">
    <el-alert type="info" :closable="false" style="margin-bottom: 10px"
              title="勾选要退回的行并填写数量（默认=可退数量）。生成的是草稿入库单，类型「退库入库」，审核后才会增加库存。" />
    <div class="line">
      <span class="muted">出库单：{{ info.doc_no }}（{{ info.warehouse_name || '—' }} / {{ info.out_type }}）</span>
      <span style="flex: 1"></span>
      <span class="muted">退库日期</span>
      <el-date-picker v-model="docDate" type="date" value-format="YYYY-MM-DD" size="small"
                      style="width: 140px" />
    </div>

    <el-table v-loading="loading" :data="rows" border stripe size="small" max-height="380">
      <el-table-column width="46">
        <template #header>
          <el-checkbox :model-value="rows.length > 0 && rows.every((r) => !(Number(r.returnable_qty) > 0) || r.checked)"
                       :indeterminate="rows.some((r) => r.checked) && !rows.every((r) => r.checked)"
                       @change="(v: boolean | string | number) => toggleAll(Boolean(v))" />
        </template>
        <template #default="{ row }">
          <el-checkbox v-model="row.checked" :disabled="Number(row.returnable_qty) <= 0" />
        </template>
      </el-table-column>
      <el-table-column label="物料" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.product_name }}<span class="muted">（{{ row.product_code }}）</span>
          <span v-if="row.spec" class="muted"> / {{ row.spec }}</span>
        </template>
      </el-table-column>
      <el-table-column label="单位" width="70">
        <template #default="{ row }">{{ row.uom_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="已出库" width="90" align="right">
        <template #default="{ row }">{{ fmtQty(row.qty, decimalsOf(row)) }}</template>
      </el-table-column>
      <el-table-column label="已退" width="90" align="right">
        <template #default="{ row }">{{ fmtQty(row.returned_qty, decimalsOf(row)) }}</template>
      </el-table-column>
      <el-table-column label="可退" width="90" align="right">
        <template #default="{ row }">
          <b :class="{ zero: Number(row.returnable_qty) <= 0 }">
            {{ fmtQty(row.returnable_qty, decimalsOf(row)) }}
          </b>
        </template>
      </el-table-column>
      <el-table-column label="本次退库" width="150">
        <template #default="{ row }">
          <el-input-number v-model="row.return_qty" size="small" :controls="false"
                           :min="0" :max="Number(row.returnable_qty)"
                           :precision="decimalsOf(row)" :disabled="!row.checked"
                           style="width: 100%" @change="clampQty(row)" />
        </template>
      </el-table-column>
      <template #empty>该出库单没有可退行（可能已全部退库）</template>
    </el-table>

    <div class="line" style="margin-top: 10px">
      <el-input v-model="remark" placeholder="退库说明（可选）" maxlength="200" />
      <span class="muted" style="white-space: nowrap">合计数量：{{ fmtQty(totalQty) }}</span>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" :disabled="!selectedRows.length"
                 @click="submit">生成退库入库单</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.line { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.muted { color: var(--el-text-color-secondary); font-size: 12px; }
.zero { color: var(--el-text-color-placeholder); }
</style>
