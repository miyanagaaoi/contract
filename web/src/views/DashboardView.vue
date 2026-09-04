<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { fetchDashboard, updateContract, type Dict } from '@/api'

const router = useRouter()
const data = ref<Dict>({ stats: {}, expiring: [], expired: [] })
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    data.value = await fetchDashboard()
  } finally {
    loading.value = false
  }
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

    <el-row :gutter="12">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>🟡 质保即将到期（30 天内）</template>
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
.num { font-size: 28px; font-weight: 700; color: #303133; }
.card.warn .num { color: #e6a23c; }
.card.danger .num { color: #f56c6c; }
.label { color: #909399; font-size: 13px; margin-top: 4px; }
</style>
