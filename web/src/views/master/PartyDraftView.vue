<script setup lang="ts">
/**
 * 历史档案认领（T-V2-14 / AC-V2-35）。
 *
 * 流程：扫描历史合同甲乙方文本 → 生成"待认领"草案 → 管理员确认（新建档案 / 绑定已有档案）
 * → 系统批量把对应历史合同的 customer_id / supplier_id 写入并记录变更历史。
 * 未认领的合同继续以纯文本展示（AC-V2-34），不影响日常使用。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  claimPartyDraft,
  fetchMasterOptions,
  fetchPartyDrafts,
  ignorePartyDraft,
  migrateParties,
  type Dict,
} from '@/api'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canEdit = computed(() => auth.hasPerm('contract.edit'))

const status = ref<'pending' | 'claimed' | 'ignored' | 'all'>('pending')
const rows = ref<Dict[]>([])
const counts = ref<Dict>({ pending: 0, claimed: 0, ignored: 0 })
const loading = ref(false)
const scanning = ref(false)

const dialogVisible = ref(false)
const saving = ref(false)
const current = ref<Dict | null>(null)
const form = reactive<Dict>({ mode: 'create', name: '', code: '', contact_name: '', contact_phone: '', target_id: '' })
const candidates = ref<Dict[]>([])

async function load() {
  loading.value = true
  try {
    const data = await fetchPartyDrafts(status.value)
    rows.value = data.items
    counts.value = data.counts
  } finally {
    loading.value = false
  }
}

async function scan() {
  scanning.value = true
  try {
    const result = await migrateParties()
    ElMessage.success(`扫描完成：新增草案 ${result.created} 条，刷新 ${result.refreshed} 条，待认领 ${result.pending} 条`)
    status.value = 'pending'
    await load()
  } finally {
    scanning.value = false
  }
}

async function openClaim(row: Dict) {
  current.value = row
  form.mode = row.candidates?.length ? 'link' : 'create'
  form.name = row.raw_name
  form.code = ''
  form.contact_name = ''
  form.contact_phone = ''
  form.target_id = row.candidates?.[0]?.id || ''
  dialogVisible.value = true
  // 候选：同名档案 + 该方向全部档案（供手工挑选）
  candidates.value = await fetchMasterOptions(row.party_type)
}

async function submitClaim() {
  if (!current.value) return
  if (form.mode === 'create' && !form.name) return ElMessage.warning('请填写档案名称')
  if (form.mode === 'link' && !form.target_id) return ElMessage.warning('请选择要绑定的档案')
  saving.value = true
  try {
    const payload = form.mode === 'link'
      ? { action: 'link', target_id: form.target_id }
      : { action: 'create', name: form.name, code: form.code || undefined,
          contact_name: form.contact_name || undefined, contact_phone: form.contact_phone || undefined }
    const result = await claimPartyDraft(current.value.id, payload)
    ElMessage.success(`已认领「${result.archive.name}」，批量绑定合同 ${result.bound} 张`)
    dialogVisible.value = false
    await load()
  } catch {
    // 拦截器已提示
  } finally {
    saving.value = false
  }
}

async function doIgnore(row: Dict) {
  let reason = ''
  try {
    const result = await ElMessageBox.prompt(
      `忽略后「${row.raw_name}」不再提示，相关合同继续以文本展示。可填写说明：`,
      '忽略草案', { confirmButtonText: '确定忽略', cancelButtonText: '取消', inputPlaceholder: '可选' },
    )
    reason = result.value || ''
  } catch {
    return
  }
  await ignorePartyDraft(row.id, reason)
  ElMessage.success('已忽略')
  await load()
}

function statusTag(value: string) {
  return value === 'pending' ? 'warning' : value === 'claimed' ? 'success' : 'info'
}

function statusText(value: string) {
  return { pending: '待认领', claimed: '已认领', ignored: '已忽略' }[value] || value
}

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="head">
        <div>
          <span class="title">历史档案认领</span>
          <span class="subtitle">
            把 V1.0 合同的甲乙方纯文本整理为客户/供应商档案（不强制；未认领不影响使用）
          </span>
        </div>
        <el-button v-if="canEdit" type="primary" :loading="scanning" @click="scan">扫描历史文本</el-button>
      </div>
    </template>

    <el-alert type="info" :closable="false" show-icon class="mb12"
              title="迁移不修改合同金额与条款，只补充 customer_id / supplier_id；逐张合同会写入带操作人的变更历史。" />

    <el-radio-group v-model="status" class="mb12" @change="load">
      <el-radio-button value="pending">待认领（{{ counts.pending }}）</el-radio-button>
      <el-radio-button value="claimed">已认领（{{ counts.claimed }}）</el-radio-button>
      <el-radio-button value="ignored">已忽略（{{ counts.ignored }}）</el-radio-button>
      <el-radio-button value="all">全部</el-radio-button>
    </el-radio-group>

    <el-table v-loading="loading" :data="rows" border stripe size="small">
      <el-table-column label="方向" width="90">
        <template #default="{ row }">
          <el-tag :type="row.party_type === 'supplier' ? 'warning' : 'success'" size="small">
            {{ row.party_label }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="raw_name" label="合同中的文本" min-width="220" show-overflow-tooltip />
      <el-table-column prop="contract_count" label="涉及合同" width="100" />
      <el-table-column label="同名档案" min-width="160">
        <template #default="{ row }">
          <el-tag v-for="c in row.candidates" :key="c.id" size="small" class="mr4">
            {{ c.name }}（{{ c.code }}）
          </el-tag>
          <span v-if="!row.candidates?.length" class="gray">无</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="remark" label="处理说明" min-width="130" show-overflow-tooltip />
      <el-table-column v-if="canEdit" label="操作" width="170" fixed="right">
        <template #default="{ row }">
          <template v-if="row.status === 'pending'">
            <el-button link type="primary" size="small" @click="openClaim(row)">认领</el-button>
            <el-button link type="info" size="small" @click="doIgnore(row)">忽略</el-button>
          </template>
          <span v-else class="gray">已处理</span>
        </template>
      </el-table-column>
      <template #empty>暂无草案，点击右上角「扫描历史文本」生成</template>
    </el-table>

    <el-dialog v-model="dialogVisible" title="认领历史档案" width="560px">
      <el-form label-width="110px">
        <el-form-item label="合同文本">
          <span>{{ current?.raw_name }}（{{ current?.contract_count }} 张合同）</span>
        </el-form-item>
        <el-form-item label="处理方式">
          <el-radio-group v-model="form.mode">
            <el-radio value="create">新建档案</el-radio>
            <el-radio value="link">绑定已有档案</el-radio>
          </el-radio-group>
        </el-form-item>
        <template v-if="form.mode === 'create'">
          <el-form-item label="档案名称" required><el-input v-model="form.name" /></el-form-item>
          <el-form-item label="档案编码">
            <el-input v-model="form.code" placeholder="留空自动生成" />
          </el-form-item>
          <el-form-item label="联系人"><el-input v-model="form.contact_name" /></el-form-item>
          <el-form-item label="联系电话"><el-input v-model="form.contact_phone" /></el-form-item>
        </template>
        <template v-else>
          <el-form-item label="目标档案" required>
            <el-select v-model="form.target_id" filterable style="width: 100%">
              <el-option v-for="o in candidates" :key="o.id" :label="`${o.name}（${o.code}）`" :value="o.id" />
            </el-select>
          </el-form-item>
        </template>
        <div class="gray">认领后系统会自动把匹配的历史合同绑定到该档案（仅补 id，不改金额与条款）。</div>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitClaim">确认认领</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; }
.title { font-weight: 600; font-size: 15px; }
.subtitle { margin-left: 10px; color: #909399; font-size: 12.5px; }
.mb12 { margin-bottom: 12px; }
.mr4 { margin-right: 4px; }
.gray { color: #909399; font-size: 12.5px; }
</style>
