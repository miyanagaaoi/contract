<script setup lang="ts">
/**
 * 库存明细（T-V2-25 / AC-V2-25~26）。
 *
 * - 结存列表：关键词 / 仓库 / 商品类型 / 仅低于安全库存筛选，`below_safety` 行高亮；
 * - 点击行 → 抽屉展示该「物料 + 仓库」的**流水下钻**（业务类型 / 来源单号 / 变动量 / 变动后结存 / 时间）；
 * - 「库存重算」：校验 `stocks.qty == SUM(ledger.qty_change)`，展示校验结果，可选按流水修复。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  downloadBlobFile,
  fetchBalances,
  fetchLedger,
  fetchMasterOptions,
  recalcStock,
  type Dict,
} from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { StockBalance, StockLedgerResult } from '@/types/doc'

const auth = useAuthStore()
const canRecalc = computed(() => auth.hasPerm('stock.balance.view'))
/** 导出结存与结存列表同权限；流水导出需 `stock.ledger.view` */
const canExportBalance = computed(() => auth.hasPerm('stock.balance.view'))
/** 流水下钻需 `stock.ledger.view`；无权限时给出明确提示而不是静默失败 */
const canLedger = computed(() => auth.hasPerm('stock.ledger.view'))

const rows = ref<StockBalance[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)

const query = reactive({
  keyword: '',
  warehouse_id: null as number | null,
  product_type_id: null as number | null,
  below_safety: false,
  // V2.1 / N12：结存数量区间筛选
  qty_min: null as number | null,
  qty_max: null as number | null,
})

const warehouses = ref<Dict[]>([])
const productTypes = ref<Dict[]>([])

const recalcLoading = ref(false)
const recalcResult = ref<Dict | null>(null)

async function load() {
  loading.value = true
  try {
    const data = await fetchBalances({
      keyword: query.keyword || undefined,
      warehouse_id: query.warehouse_id || undefined,
      product_type_id: query.product_type_id || undefined,
      below_safety: query.below_safety || undefined,
      qty_min: query.qty_min ?? undefined,
      qty_max: query.qty_max ?? undefined,
      page: page.value,
      page_size: pageSize.value,
    })
    rows.value = data.items ?? []
    total.value = data.total ?? rows.value.length
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function resetQuery() {
  query.keyword = ''
  query.warehouse_id = null
  query.product_type_id = null
  query.below_safety = false
  query.qty_min = null
  query.qty_max = null
  page.value = 1
  load()
}

/** 结存导出的筛选参数（与列表同口径，AC-V2-40） */
function balanceParams(): Dict {
  return {
    keyword: query.keyword || undefined,
    warehouse_id: query.warehouse_id || undefined,
    product_type_id: query.product_type_id || undefined,
    below_safety: query.below_safety || undefined,
    qty_min: query.qty_min ?? undefined,
    qty_max: query.qty_max ?? undefined,
  }
}

// ---------------- 导出 ----------------
const exportLoading = ref(false)
const ledgerExportLoading = ref(false)

/** 导出结存（令牌在请求头，必须走 blob 下载） */
async function exportBalances() {
  exportLoading.value = true
  try {
    await downloadBlobFile('/api/stock/balances/export.xlsx', balanceParams(), '库存结存.xlsx')
    ElMessage.success('已开始下载结存清单')
  } catch {
    // 拦截器已提示
  } finally {
    exportLoading.value = false
  }
}

/** 导出当前「物料 + 仓库」的库存流水 */
async function exportLedger() {
  if (!current.value) return
  ledgerExportLoading.value = true
  try {
    await downloadBlobFile('/api/stock/ledger/export.xlsx', {
      product_id: current.value.product_id,
      warehouse_id: current.value.warehouse_id,
      date_from: ledgerQuery.date_range?.[0] || undefined,
      date_to: ledgerQuery.date_range?.[1] || undefined,
    }, '库存流水.xlsx')
    ElMessage.success('已开始下载库存流水')
  } catch {
    // 拦截器已提示
  } finally {
    ledgerExportLoading.value = false
  }
}

/** 低于安全库存行高亮 */
function rowClass({ row }: { row: StockBalance }): string {
  return row.below_safety ? 'below-safety-row' : ''
}

function fmtQty(v: unknown, decimals: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  const d = decimals === null || decimals === undefined ? 2 : Number(decimals)
  return n.toFixed(Math.max(0, Math.min(6, d)))
}

function fmtMoney(v: unknown): string {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  return Number.isNaN(n) ? String(v) : n.toFixed(2)
}

function fmtDate(v: unknown): string {
  return v ? String(v).slice(0, 19) : '—'
}

// ---------------- 流水下钻 ----------------
const drawerVisible = ref(false)
const ledgerLoading = ref(false)
const ledger = ref<StockLedgerResult | null>(null)
const current = ref<StockBalance | null>(null)
const ledgerQuery = reactive({ date_range: [] as string[], page: 1, page_size: 20 })

async function loadLedger() {
  if (!current.value) return
  ledgerLoading.value = true
  try {
    ledger.value = await fetchLedger({
      product_id: current.value.product_id,
      warehouse_id: current.value.warehouse_id,
      date_from: ledgerQuery.date_range?.[0] || undefined,
      date_to: ledgerQuery.date_range?.[1] || undefined,
      page: ledgerQuery.page,
      page_size: ledgerQuery.page_size,
    })
  } catch {
    ledger.value = null
  } finally {
    ledgerLoading.value = false
  }
}

async function openLedger(row: StockBalance) {
  current.value = row
  ledgerQuery.date_range = []
  ledgerQuery.page = 1
  drawerVisible.value = true
  await loadLedger()
}

// ---------------- 库存重算 ----------------
async function doRecalc(fix = false) {
  if (fix) {
    try {
      await ElMessageBox.confirm(
        '将按库存流水修复结存数量（不改动流水与单据）。确定继续？',
        '库存重算修复', { type: 'warning', confirmButtonText: '确定修复', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
  }
  recalcLoading.value = true
  try {
    recalcResult.value = await recalcStock(fix)
    const r = recalcResult.value
    if (r.consistent) ElMessage.success(`校验通过：共检查 ${r.checked} 行，无差异`)
    else ElMessage.warning(`发现 ${r.mismatch_count} 行结存与流水不一致${r.fixed ? '（已修复）' : ''}`)
    await load()
  } catch {
    // 拦截器已提示
  } finally {
    recalcLoading.value = false
  }
}

onMounted(async () => {
  try {
    const [w, t] = await Promise.all([
      fetchMasterOptions('warehouse'),
      fetchMasterOptions('product-type'),
    ])
    warehouses.value = w
    productTypes.value = t
  } catch {
    // 下拉失败不阻塞列表
  }
  await load()
})
</script>

<template>
  <div>
    <el-card shadow="never" class="mb">
      <template #header>
        <div class="head">
          <div>
            <span class="title">库存明细</span>
            <span class="subtitle">结存 + 流水下钻；低于安全库存的行会高亮</span>
          </div>
          <div>
            <el-button v-if="canExportBalance" :loading="exportLoading" @click="exportBalances">
              <el-icon><Download /></el-icon>导出结存
            </el-button>
            <el-button v-if="canRecalc" :loading="recalcLoading" @click="doRecalc(false)">库存重算</el-button>
          </div>
        </div>
      </template>

      <el-form inline>
        <el-form-item label="关键词">
          <el-input v-model="query.keyword" placeholder="物料编码 / 名称 / 规格" clearable
                    style="width: 200px" @keyup.enter="page = 1; load()" />
        </el-form-item>
        <el-form-item label="仓库">
          <el-select v-model="query.warehouse_id" clearable filterable style="width: 160px"
                     @change="page = 1; load()">
            <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="商品类型">
          <el-select v-model="query.product_type_id" clearable filterable style="width: 170px"
                     @change="page = 1; load()">
            <el-option v-for="t in productTypes" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量区间">
          <el-input-number v-model="query.qty_min" :controls="false" placeholder="下限"
                           style="width: 90px" @change="page = 1; load()" />
          <span style="margin: 0 6px; color: #909399">~</span>
          <el-input-number v-model="query.qty_max" :controls="false" placeholder="上限"
                           style="width: 90px" @change="page = 1; load()" />
        </el-form-item>
        <el-form-item label="仅低于安全库存">
          <el-switch v-model="query.below_safety" @change="page = 1; load()" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="page = 1; load()">查询</el-button>
          <el-button @click="resetQuery">重置</el-button>
        </el-form-item>
      </el-form>

      <el-alert v-if="recalcResult" class="mb" :closable="true" type="info" show-icon
                @close="recalcResult = null"
                :title="`库存重算：检查 ${recalcResult.checked} 行，不一致 ${recalcResult.mismatch_count} 行${recalcResult.fixed ? '（已按流水修复）' : ''}`">
        <div v-if="recalcResult.mismatch_count">
          不一致明细：
          <span v-for="(m, i) in recalcResult.mismatches" :key="i" class="mismatch">
            物料 {{ m.product_id }} / 仓库 {{ m.warehouse_id }}：结存 {{ m.qty }}，流水 {{ m.ledger_qty }}
          </span>
          <el-button v-if="canRecalc" link type="primary" class="ml" @click="doRecalc(true)">按流水修复</el-button>
        </div>
      </el-alert>
    </el-card>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="rows" border stripe size="small"
                :row-class-name="rowClass" @row-click="openLedger">
        <el-table-column type="index" label="#" width="52" />
        <el-table-column prop="product_code" label="物料编码" width="140" show-overflow-tooltip />
        <el-table-column prop="product_name" label="物料名称" min-width="150" show-overflow-tooltip />
        <el-table-column prop="spec" label="规格型号" min-width="120" show-overflow-tooltip />
        <el-table-column prop="product_type_name" label="商品类型" width="120" show-overflow-tooltip />
        <el-table-column label="单位" width="70">
          <template #default="{ row }">{{ row.uom_name || '—' }}</template>
        </el-table-column>
        <el-table-column prop="warehouse_name" label="仓库" width="130" show-overflow-tooltip />
        <el-table-column label="结存数量" width="110" align="right">
          <template #default="{ row }">
            <span :class="{ danger: row.below_safety }">{{ fmtQty(row.qty, row.uom_decimals) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="安全库存" width="110" align="right">
          <template #default="{ row }">
            {{ row.safety_stock === null || row.safety_stock === undefined ? '—' : fmtQty(row.safety_stock, row.uom_decimals) }}
          </template>
        </el-table-column>
        <el-table-column label="货品总额度" width="130" align="right">
          <!-- V2.1 / N11：该 (物料 × 仓库) 的入库批次金额合计（BR-V2.1-09） -->
          <template #default="{ row }">{{ fmtMoney(row.inbound_amount) }}</template>
        </el-table-column>
        <el-table-column label="库存状态" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.below_safety" type="danger" size="small">低于安全</el-tag>
            <el-tag v-else type="success" size="small">正常</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="160">
          <template #default="{ row }">{{ fmtDate(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small"
                       @click.stop="openLedger(row)">流水下钻</el-button>
          </template>
        </el-table-column>
        <template #empty>暂无库存结存数据</template>
      </el-table>

      <el-pagination v-if="total > pageSize" class="pager" background
                     layout="total, prev, pager, next, sizes" :total="total"
                     :current-page="page" :page-size="pageSize" :page-sizes="[10, 20, 50, 100]"
                     @current-change="(p: number) => { page = p; load() }"
                     @size-change="(s: number) => { pageSize = s; page = 1; load() }" />
    </el-card>

    <!-- 流水下钻抽屉 -->
    <el-drawer v-model="drawerVisible" size="820px"
               :title="`库存流水 · ${current?.product_name ?? ''} @ ${current?.warehouse_name ?? ''}`">
      <div v-if="current">
        <el-descriptions :column="3" border size="small" class="mb">
          <el-descriptions-item label="物料编码">{{ current.product_code || '—' }}</el-descriptions-item>
          <el-descriptions-item label="规格型号">{{ current.spec || '—' }}</el-descriptions-item>
          <el-descriptions-item label="单位">{{ current.uom_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="仓库">{{ current.warehouse_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="当前结存">
            <b>{{ fmtQty(ledger?.balance ?? current.qty, current.uom_decimals) }}</b>
          </el-descriptions-item>
          <el-descriptions-item label="安全库存">
            {{ current.safety_stock === null || current.safety_stock === undefined ? '—' : fmtQty(current.safety_stock, current.uom_decimals) }}
          </el-descriptions-item>
        </el-descriptions>

        <el-form inline>
          <el-form-item label="日期区间">
            <el-date-picker v-model="ledgerQuery.date_range" type="daterange" value-format="YYYY-MM-DD"
                            start-placeholder="开始" end-placeholder="结束" style="width: 230px"
                            @change="ledgerQuery.page = 1; loadLedger()" />
          </el-form-item>
          <el-form-item>
            <el-button @click="ledgerQuery.date_range = []; ledgerQuery.page = 1; loadLedger()">重置</el-button>
            <el-button v-if="canLedger" :loading="ledgerExportLoading" @click="exportLedger">
              <el-icon><Download /></el-icon>导出流水
            </el-button>
          </el-form-item>
        </el-form>

        <el-alert v-if="!canLedger" type="warning" :closable="false" show-icon class="mb"
                  title="你没有「库存流水查看」（stock.ledger.view）权限，流水可能无法加载。" />

        <el-table v-loading="ledgerLoading" :data="ledger?.items ?? []" border stripe size="small">
          <el-table-column label="时间" width="150">
            <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
          </el-table-column>
          <el-table-column prop="biz_type" label="业务类型" width="100">
            <template #default="{ row }">{{ row.biz_type || '—' }}</template>
          </el-table-column>
          <el-table-column label="单据类型" width="100">
            <template #default="{ row }">{{ row.doc_type || '—' }}</template>
          </el-table-column>
          <el-table-column prop="doc_no" label="来源单号" width="150" show-overflow-tooltip>
            <template #default="{ row }">{{ row.doc_no || row.src_doc_no || '—' }}</template>
          </el-table-column>
          <el-table-column label="变动量" width="100" align="right">
            <template #default="{ row }">
              <span :class="Number(row.qty_change) >= 0 ? 'plus' : 'minus'">
                {{ Number(row.qty_change) >= 0 ? '+' : '' }}{{ fmtQty(row.qty_change, current?.uom_decimals) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="变动后结存" width="110" align="right">
            <template #default="{ row }">{{ fmtQty(row.qty_after, current?.uom_decimals) }}</template>
          </el-table-column>
          <el-table-column label="单价" width="90" align="right">
            <template #default="{ row }">{{ row.unit_price === null ? '—' : fmtMoney(row.unit_price) }}</template>
          </el-table-column>
          <el-table-column prop="remark" label="备注" min-width="130" show-overflow-tooltip>
            <template #default="{ row }">{{ row.remark || '—' }}</template>
          </el-table-column>
          <template #empty>暂无流水记录</template>
        </el-table>

        <el-pagination v-if="(ledger?.total ?? 0) > 0" class="pager" background
                       layout="total, prev, pager, next" :total="ledger?.total ?? 0"
                       :current-page="ledgerQuery.page" :page-size="ledgerQuery.page_size"
                       @current-change="(p: number) => { ledgerQuery.page = p; loadLedger() }" />
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.mb { margin-bottom: 12px; }
.ml { margin-left: 8px; }
.head { display: flex; align-items: center; justify-content: space-between; }
.title { font-weight: 600; font-size: 15px; }
.subtitle { margin-left: 10px; color: #909399; font-size: 12.5px; }
.pager { margin-top: 12px; justify-content: flex-end; }
.mismatch { margin-right: 12px; color: #e6a23c; }
.danger { color: #f56c6c; font-weight: 600; }
.plus { color: #67c23a; }
.minus { color: #f56c6c; }
:deep(.below-safety-row td) { background: #fef0f0 !important; }
:deep(.el-table__row) { cursor: pointer; }
</style>
