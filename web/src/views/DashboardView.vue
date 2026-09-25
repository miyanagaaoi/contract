<script setup lang="ts">
/**
 * 首页看板（T9 / T-V2-38）：按角色展示待办、库存预警、质保提醒与合同执行概览。
 *
 * 数据全部来自 `GET /api/dashboard`（后端按登录人权限与数据范围裁剪后返回），
 * 前端不做权限推断，只负责展示与跳转。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { fetchDashboard, updateContract, type Dict } from '@/api'

const router = useRouter()
const data = ref<Dict>({ stats: {}, expiring: [], expired: [] })
const loading = ref(false)

// 单据类型 → 列表页路径（页面尚未开放的模块点击时给出提示，不做假跳转）
const DOC_ROUTES: Record<string, string> = {
  purchase_request: '/purchase/requests',
  purchase_order: '/purchase/orders',
  sales_request: '/sales/requests',
  sales_order: '/sales/orders',
  stock_in: '/stock/in-orders',
  stock_out: '/stock/out-orders',
  stock_take: '/stock/takes',
}

async function load() {
  loading.value = true
  try {
    data.value = await fetchDashboard()
  } finally {
    loading.value = false
  }
}

const todo = computed<Dict>(() => data.value.todo || {})
const stockAlerts = computed<Dict>(() => data.value.stock_alerts || { available: false, items: [] })
const overview = computed<Dict>(() => data.value.contract_overview || {})

function routeOf(docType: string): string | null {
  const path = DOC_ROUTES[docType]
  if (!path) return null
  const resolved = router.resolve(path)
  const fallback = resolved.matched.some((r) => String(r.path).includes('pathMatch'))
  return fallback ? null : path
}

function goDoc(row: Dict) {
  const path = routeOf(row.doc_type)
  if (!path) {
    ElMessage.info(`「${row.kind_label || row.doc_type}」页面尚未开放（见开发计划 M3）`)
    return
  }
  router.push(path)
}

/** 跳转到已开放的页面；目标路由未注册时给出提示而不是静默回到首页 */
function goPath(path: string) {
  const resolved = router.resolve(path)
  const fallback = resolved.matched.some((r) => String(r.path).includes('pathMatch'))
  if (fallback) {
    ElMessage.info('该页面尚未开放')
    return
  }
  router.push(path)
}

async function markReleased(row: Dict) {
  try {
    await ElMessageBox.confirm(
      `确认质保金已释放/处理？「${row.name}」（到期 ${row.warranty_end}）将不再提醒。`,
      '质保释放确认',
      { type: 'warning', confirmButtonText: '标记已释放', cancelButtonText: '取消' },
    )
    const today = new Date().toISOString().slice(0, 10)
    await updateContract(row.id, { warranty_released: true, warranty_release_date: today })
    ElMessage.success('已标记释放')
    load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') throw e
  }
}

function fmtDate(s: string | null | undefined): string {
  return s ? String(s).slice(0, 10) : '—'
}

function fmtMoney(v: unknown): string {
  const n = Number(v || 0)
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <!-- 统计卡 -->
    <el-row :gutter="12" class="mb">
      <el-col :span="6">
        <el-card shadow="never" class="card"><div class="num">{{ data.stats.total ?? 0 }}</div><div class="label">合同总数（有效）</div></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="card"><div class="num">{{ data.stats.frameworks ?? 0 }}</div><div class="label">框架合同</div></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="card warn"><div class="num">{{ data.stats.expiring_count ?? 0 }}</div><div class="label">质保即将到期（{{ data.stats.window_days ?? 30 }} 天内）</div></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="card danger"><div class="num">{{ data.stats.expired_count ?? 0 }}</div><div class="label">质保已到期（未处理）</div></el-card>
      </el-col>
    </el-row>

    <!-- 按角色待办 -->
    <el-row :gutter="12" class="mb">
      <el-col :span="8">
        <el-card shadow="never" class="card todo">
          <div class="num">{{ todo.to_approve?.total ?? 0 }}</div>
          <div class="label">待我审核</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never" class="card">
          <div class="num">{{ todo.my_submitted?.total ?? 0 }}</div>
          <div class="label">我提交的（待审核）</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never" class="card">
          <div class="num">{{ todo.my_draft?.total ?? 0 }}</div>
          <div class="label">我的草稿</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="12" class="mb">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>
            <span>📝 待我审核</span>
            <span class="sub">（受数据范围限制）</span>
          </template>
          <el-empty v-if="!(todo.to_approve?.items || []).length" description="暂无待审核单据" :image-size="60" />
          <el-table v-else :data="todo.to_approve.items" size="small" border>
            <el-table-column prop="kind_label" label="类型" width="100" />
            <el-table-column prop="doc_no" label="单号" width="150">
              <template #default="{ row }">
                <el-button link type="primary" @click="goDoc(row)">{{ row.doc_no }}</el-button>
              </template>
            </el-table-column>
            <el-table-column prop="party" label="往来单位" min-width="120" show-overflow-tooltip />
            <el-table-column label="金额" width="100">
              <template #default="{ row }">{{ fmtMoney(row.total_amount) }}</template>
            </el-table-column>
            <el-table-column prop="created_by_name" label="提交人" width="100" />
          </el-table>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card shadow="never">
          <template #header>
            <span>📦 库存预警</span>
            <span class="sub">（低于安全库存）</span>
          </template>
          <el-empty v-if="!stockAlerts.available" description="无库存查看权限" :image-size="60" />
          <el-empty v-else-if="!(stockAlerts.items || []).length" description="库存充足" :image-size="60" />
          <el-table v-else :data="stockAlerts.items" size="small" border>
            <el-table-column prop="product_code" label="物料编码" width="130" />
            <el-table-column prop="product_name" label="物料" min-width="130" show-overflow-tooltip />
            <el-table-column prop="warehouse_name" label="仓库" width="110" />
            <el-table-column prop="qty" label="结存" width="80" />
            <el-table-column label="安全库存" width="90">
              <template #default="{ row }">{{ row.safety_stock }}</template>
            </el-table-column>
            <el-table-column label="缺口" width="80">
              <template #default="{ row }">
                <el-tag type="danger" size="small">{{ row.shortage }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
          <div v-if="stockAlerts.available" class="foot">
            共 {{ stockAlerts.total ?? 0 }} 条低于安全库存
            <el-button link type="primary" @click="goPath('/stock/balances')">查看库存明细</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 合同执行概览 -->
    <el-card shadow="never" class="mb">
      <template #header>📊 合同执行概览<span class="sub">（受数据范围限制）</span></template>
      <el-row :gutter="12">
        <el-col :span="4"><div class="ov"><div class="ovnum">{{ overview.total ?? 0 }}</div><div class="label">合同数</div></div></el-col>
        <el-col :span="4"><div class="ov"><div class="ovnum">{{ overview.frameworks ?? 0 }}</div><div class="label">框架合同</div></div></el-col>
        <el-col :span="5"><div class="ov"><div class="ovnum">{{ fmtMoney(overview.amount_sum) }}</div><div class="label">合同金额合计</div></div></el-col>
        <el-col :span="5"><div class="ov"><div class="ovnum">{{ fmtMoney(overview.paid_sum) }}</div><div class="label">累计已付合计</div></div></el-col>
        <el-col :span="3"><div class="ov"><div class="ovnum">{{ overview.paid_ratio ?? '—' }}<span v-if="overview.paid_ratio !== null && overview.paid_ratio !== undefined">%</span></div><div class="label">付款比例</div></div></el-col>
        <el-col :span="3"><div class="ov"><div class="ovnum">{{ overview.warranty_open ?? 0 }}</div><div class="label">质保在保</div></div></el-col>
      </el-row>
      <div class="statuses">
        <el-tag v-for="s in overview.by_status || []" :key="s.status" size="small" class="mr4">
          {{ s.status }} {{ s.count }}
        </el-tag>
      </div>
    </el-card>

    <!-- 质保提醒 -->
    <el-row :gutter="12">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>🟡 质保即将到期（{{ data.stats.window_days ?? 30 }} 天内）</template>
          <el-empty v-if="!data.expiring.length" description="暂无即将到期" :image-size="60" />
          <el-table v-else :data="data.expiring" size="small" border>
            <el-table-column prop="contract_no" label="编号" width="130" />
            <el-table-column prop="name" label="合同" min-width="150" show-overflow-tooltip />
            <el-table-column label="质保到期" width="100">
              <template #default="{ row }">{{ fmtDate(row.warranty_end) }}</template>
            </el-table-column>
            <el-table-column label="剩余天数" width="90">
              <template #default="{ row }">
                <el-tag v-if="(row.days_left ?? 0) <= 10" type="danger" size="small">{{ row.days_left }} 天</el-tag>
                <span v-else>{{ row.days_left }} 天</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button link type="primary" @click="markReleased(row)">标记已释放</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>🔴 质保已到期（未处理）</template>
          <el-empty v-if="!data.expired.length" description="暂无已到期" :image-size="60" />
          <el-table v-else :data="data.expired" size="small" border>
            <el-table-column prop="contract_no" label="编号" width="130" />
            <el-table-column prop="name" label="合同" min-width="150" show-overflow-tooltip />
            <el-table-column label="质保到期" width="100">
              <template #default="{ row }">{{ fmtDate(row.warranty_end) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="80">
              <template #default="{ row }">{{ row.status }}</template>
            </el-table-column>
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button link type="primary" @click="markReleased(row)">标记已释放</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-alert class="mt" type="info" :closable="false" show-icon
      title="到合同台账" description="完整搜索/筛选/导出请前往合同台账页。"
      @click="router.push('/contracts')" style="cursor: pointer" />
  </div>
</template>

<style scoped>
.mb { margin-bottom: 12px; }
.mt { margin-top: 12px; }
.card { text-align: center; }
.card.todo .num { color: #409eff; }
.num { font-size: 28px; font-weight: 700; color: #303133; }
.card.warn .num { color: #e6a23c; }
.card.danger .num { color: #f56c6c; }
.label { color: #909399; font-size: 13px; margin-top: 4px; }
.sub { color: #909399; font-size: 12.5px; margin-left: 6px; }
.foot { margin-top: 8px; color: #909399; font-size: 12.5px; }
.ov { text-align: center; }
.ovnum { font-size: 20px; font-weight: 600; color: #303133; }
.statuses { margin-top: 12px; }
.mr4 { margin-right: 4px; }
</style>
