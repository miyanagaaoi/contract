<script setup lang="ts">
/**
 * 调拨单表单（V2.1 / N13）。
 *
 * 调出仓 / 调入仓均必填且**不得相同**（前后端双重校验：后端见
 * `app/routers/stock.py::_apply_transfer_fields`，防止绕过前端）。
 * CR-031：行项**显示并允许编辑单价**（默认按调出仓 FIFO 成本带出，可手工改）；
 * 两端同价过账，保证跨仓「当前库存总额度」守恒。
 *
 * V2.3（N4）：调出单位 / 调入单位由两端仓库的**所属公司**自动带出（只读，后端落快照），
 * 让跨公司调拨一眼能看出货物归属变化；仓库下拉统一显示 `主体码-仓库名`。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import DocFormPage from '@/components/doc/DocFormPage.vue'
import { fetchMasterOptions, http, type Dict } from '@/api'

const extra = ref<Dict>({
  from_warehouse_id: null,
  to_warehouse_id: null,
})

const warehouses = ref<Dict[]>([])
const formRef = ref<InstanceType<typeof DocFormPage> | null>(null)

async function ensureOptions() {
  if (warehouses.value.length) return
  try {
    warehouses.value = await fetchMasterOptions('warehouse')
  } catch {
    warehouses.value = []
  }
}
void ensureOptions()

/** 调出单位：调出仓所属公司（未维护所属公司时显示 —） */
const fromUnit = computed(() => {
  const hit = warehouses.value.find((w) => w.id === Number(extra.value.from_warehouse_id))
  return (hit?.subject_name as string) || '—'
})

/** 调入单位：调入仓所属公司 */
const toUnit = computed(() => {
  const hit = warehouses.value.find((w) => w.id === Number(extra.value.to_warehouse_id))
  return (hit?.subject_name as string) || '—'
})

// ---------------- CR-031：调拨单价默认带出「调出仓 FIFO 成本」 ----------------
let fifoTimer: ReturnType<typeof setTimeout> | null = null

function scheduleFifoFill() {
  if (fifoTimer) clearTimeout(fifoTimer)
  fifoTimer = setTimeout(async () => {
    fifoTimer = null
    const wid = Number(extra.value.from_warehouse_id) || null
    const items = (formRef.value?.items as Dict[] | undefined) || []
    if (!wid) return
    for (const row of items) {
      // 只填空价：已手工填写的以用户为准
      if (!row.product_id || Number(row.unit_price) > 0) continue
      try {
        const { data } = await http.get('/stock/fifo-price', {
          params: { product_id: row.product_id, warehouse_id: wid, qty: Number(row.qty || 0) },
        })
        if (data.unit_price !== null && data.unit_price !== undefined) {
          row.unit_price = Number(data.unit_price)
        }
      } catch {
        // 带价失败不阻塞录入（可手填单价）
      }
    }
  }, 200)
}

watch([() => extra.value.from_warehouse_id, () => formRef.value?.items], scheduleFifoFill,
      { deep: true })
</script>

<template>
  <DocFormPage ref="formRef" v-model="extra" title="调拨单" kind-label="调拨单"
               api="/api/stock/transfers" perm-prefix="stock.transfer"
               list-route="stock-transfer-list" :price-on-pick="false"
               :extra-required="[{ key: 'from_warehouse_id', label: '调出仓库' },
                                 { key: 'to_warehouse_id', label: '调入仓库' }]">
    <template #header>
      <el-col :span="12">
        <el-form-item label="调出仓库" required>
          <el-select v-model="extra.from_warehouse_id" filterable placeholder="请选择调出仓库"
                     style="width: 100%" @visible-change="ensureOptions">
            <el-option v-for="w in warehouses" :key="w.id"
                       :label="(w.display_name as string) || w.name" :value="w.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="调入仓库" required>
          <el-select v-model="extra.to_warehouse_id" filterable placeholder="请选择调入仓库"
                     style="width: 100%" @visible-change="ensureOptions">
            <el-option v-for="w in warehouses" :key="w.id"
                       :label="(w.display_name as string) || w.name" :value="w.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <!-- V2.3（N4）：调出/调入单位随所选仓库自动带出（只读） -->
      <el-col :span="12">
        <el-form-item label="调出单位">
          <el-input :model-value="fromUnit" readonly placeholder="随调出仓库自动带出" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="调入单位">
          <el-input :model-value="toUnit" readonly placeholder="随调入仓库自动带出" />
        </el-form-item>
      </el-col>
      <el-col :span="24">
        <el-alert type="info" :closable="false" show-icon
                  title="审核后将在同一事务内完成：调出仓减少、调入仓增加；调出仓结存不足会被拦截。调出/调入单位由仓库所属公司自动带出。" />
      </el-col>
    </template>
  </DocFormPage>
</template>
