<script setup lang="ts">
/**
 * 出库单表单（T-V2-25）：审核即过账（负库存拦截）。
 *
 * 由销售订单下推生成时：仓库 / 出库类型 / 客户 / 行项数量已预填，
 * 单价沿用销售单价（只读），可在保存前调整出库数量。
 *
 * V2.6 新增两点（均为"体验层提前提示"，真实拦截仍由后端兜底）：
 * 1. **FIFO 自动带价**：选择物料（+仓库）后按先入先出从已过账入库批次提取加权
 *    平均单价自动填入「单价」；仅在单价为空/0 时填充，用户手改过的不覆盖；
 * 2. **保存前库存提示**：提交前按 `/api/stock/balances` 检查可用结存 ≥ 本次出库
 *    数量（同单多行同物料同仓库先合计），不足时给出中文提示并中止保存。
 */
import { watch } from 'vue'
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import DocFormPage from '@/components/doc/DocFormPage.vue'
import { fetchBalances, fetchMasterOptions, http, type Dict } from '@/api'

const formRef = ref<InstanceType<typeof DocFormPage> | null>(null)

const extra = ref<Dict>({
  warehouse_id: null,
  out_type: '销售出库',
  customer_id: null,
})

const OUT_TYPES = ['销售出库', '领用出库', '其他出库']
const warehouses = ref<Dict[]>([])
const customers = ref<Dict[]>([])

async function ensureOptions() {
  const tasks: Promise<void>[] = []
  if (!warehouses.value.length) {
    tasks.push(fetchMasterOptions('warehouse').then((v) => { warehouses.value = v }).catch(() => { warehouses.value = [] }))
  }
  if (!customers.value.length) {
    tasks.push(fetchMasterOptions('customer').then((v) => { customers.value = v }).catch(() => { customers.value = [] }))
  }
  await Promise.all(tasks)
}
void ensureOptions()

// ---------------- V2.6：FIFO 自动带价（后端 /api/stock/fifo-price） ----------------

/** 行的生效仓库：行级仓库优先，缺省回落表头仓库 */
function rowWarehouse(row: Dict): number | null {
  return (row.warehouse_id as number) || (extra.value.warehouse_id as number) || null
}

let fifoTimer: ReturnType<typeof setTimeout> | null = null

/** 行项（物料/数量/仓库）变化后，为"单价仍为空"的行拉取 FIFO 加权价（去抖合并请求） */
function scheduleFifoFill() {
  if (fifoTimer) clearTimeout(fifoTimer)
  fifoTimer = setTimeout(async () => {
    fifoTimer = null
    const items = (formRef.value?.items as Dict[] | undefined) || []
    let shortage = false
    for (const row of items) {
      const wid = rowWarehouse(row)
      // 只填空价：用户已手改（非 0）的以用户为准；累计不足时仍填已有部分的加权价并提示
      if (!row.product_id || !wid || Number(row.unit_price) > 0) continue
      try {
        const { data } = await http.get('/stock/fifo-price', {
          params: { product_id: row.product_id, warehouse_id: wid, qty: Number(row.qty || 0) },
        })
        if (data.unit_price !== null && data.unit_price !== undefined) {
          row.unit_price = Number(data.unit_price)
          if (data.enough === false) shortage = true
        }
      } catch {
        // 带价失败不阻塞录入（可手填单价）
      }
    }
    if (shortage) {
      ElMessage.warning('部分物料累计入库不足，单价按已有入库批次加权计算，请核对')
    }
  }, 200)
}

watch(() => formRef.value?.items, scheduleFifoFill, { deep: true })

// ---------------- 当前库存列（行项物料 × 表头出库仓库 的结存，只读展示） ----------------

const stockMap = ref<Record<number, number>>({})

let stockTimer: ReturnType<typeof setTimeout> | null = null

/**
 * 行项物料或表头仓库变化后，逐物料查 `/api/stock/balances?product_id=&warehouse_id=`。
 * 与 FIFO 带价一样去抖合并；仓库未选时清空映射（列内统一显示 '—'）。
 * 结存查询失败不阻塞录入（无 stock.balance.view 权限的用户仍可正常开单）。
 */
function scheduleStockRefresh() {
  if (stockTimer) clearTimeout(stockTimer)
  stockTimer = setTimeout(async () => {
    stockTimer = null
    const wid = extra.value.warehouse_id as number | null
    const items = (formRef.value?.items as Dict[] | undefined) || []
    const pids = [...new Set(items.map((r) => r.product_id as number | null).filter(Boolean))] as number[]
    if (!wid || !pids.length) {
      stockMap.value = {}
      return
    }
    const next: Record<number, number> = {}
    await Promise.all(pids.map(async (pid) => {
      try {
        const data = await fetchBalances({ product_id: pid, warehouse_id: wid, page_size: 1 })
        const hit = data.items.find((b) => b.product_id === pid)
        // 该仓库无此物料的结存记录时按 0 展示（结存表只存 qty != 0 的行）
        next[pid] = hit ? Number(hit.qty) : 0
      } catch {
        // 查不到就留空 → 该行显示 '—'
      }
    }))
    stockMap.value = next
  }, 200)
}

watch(() => [formRef.value?.items, extra.value.warehouse_id], scheduleStockRefresh, { deep: true })

// ---------------- V2.6：保存前的库存不足友好提示（后端 422 兜底） ----------------

async function checkBalance(): Promise<boolean> {
  const items = (formRef.value?.items as Dict[] | undefined) || []
  if (!items.length) return true
  // 同单多行同物料同仓库先合计，再与结存比较（口径与后端 save_validator 一致）
  const need = new Map<string, number>()
  for (const row of items) {
    const wid = rowWarehouse(row)
    if (!row.product_id || !wid) continue
    const key = `${row.product_id}-${wid}`
    need.set(key, (need.get(key) || 0) + Number(row.qty || 0))
  }
  if (!need.size) return true
  try {
    const { data } = await fetchBalances({ page_size: 200 })
    const short: string[] = []
    for (const [key, qty] of need) {
      const [pid, wid] = key.split('-').map(Number)
      const hit = data.items.find((b) => b.product_id === pid && b.warehouse_id === wid)
      const balance = hit ? Number(hit.qty) : 0
      if (balance < qty) {
        const name = hit ? `${hit.product_name}（${hit.product_code}）` : `物料#${pid}`
        short.push(`${name}：结存 ${balance}，本次出库 ${qty}`)
      }
    }
    if (short.length) {
      ElMessage.warning(`库存不足，无法保存：${short.join('；')}`)
      return false
    }
  } catch {
    // 结存查询失败（如无库存查看权限）不阻塞保存 —— 由后端保存校验/过账兜底
  }
  return true
}
</script>

<template>
  <DocFormPage ref="formRef" v-model="extra" title="出库单" kind-label="出库单"
               api="/api/stock/out-orders" perm-prefix="stock.out"
               list-route="stock-out-orders" show-subject :show-price="false" show-stock :stock-map="stockMap"
               :extra-cols="['shipped']" :before-save="checkBalance"
               :extra-required="[{ key: 'warehouse_id', label: '出库仓库' }]">
    <template #header>
      <el-col :span="12">
        <el-form-item label="出库仓库" required>
          <el-select v-model="extra.warehouse_id" filterable placeholder="请选择仓库"
                     style="width: 100%" @visible-change="ensureOptions">
            <!-- V2.3：仓库默认显示 `主体码-仓库名`（ZC-主仓） -->
            <el-option v-for="w in warehouses" :key="w.id"
                       :label="(w.display_name as string) || w.name" :value="w.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="出库类型" required>
          <el-select v-model="extra.out_type" style="width: 100%">
            <el-option v-for="t in OUT_TYPES" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="客户">
          <el-select v-model="extra.customer_id" filterable clearable
                     placeholder="销售出库建议填写" style="width: 100%" @visible-change="ensureOptions">
            <el-option v-for="c in customers" :key="c.id" :label="`${c.name}（${c.code}）`" :value="c.id" />
          </el-select>
        </el-form-item>
      </el-col>
    </template>
  </DocFormPage>
</template>
