<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createContract,
  fetchContract,
  fetchContracts,
  fetchLogs,
  getMeta,
  restoreContract,
  softDeleteContract,
  updateContract,
  type Dict,
} from '@/api'

// ---------- 状态 ----------
const rows = ref<Dict[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)

const meta = ref<Dict>({ contract_types: [], statuses: [], arrival_statuses: [] })
const frameworks = ref<Dict[]>([])

const query = reactive<Dict>({
  keyword: '',
  type: '',
  status: '',
  include_deleted: false,
})

// ---------- 列表 ----------
async function load() {
  loading.value = true
  try {
    const params: Dict = { page: page.value, page_size: pageSize.value }
    if (query.keyword) params.keyword = query.keyword
    if (query.type) params.type = query.type
    if (query.status) params.status = query.status
    if (query.include_deleted) params.include_deleted = true
    const res = await fetchContracts(params)
    rows.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function loadFrameworks() {
  const res = await fetchContracts({ page: 1, page_size: 200, is_framework: true })
  frameworks.value = res.items
}

// ---------- 新增/编辑 ----------
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const form = reactive<Dict>({
  contract_no: '', name: '', type: '采购', party_a: '', party_b: '',
  sign_date: '', subject_matter: '', amount: 0, paid_amount: 0, status: '内部审批中',
  owner_name: '', remark: '', is_framework: false, parent_id: null,
})

function resetForm() {
  Object.assign(form, {
    contract_no: '', name: '', type: '采购', party_a: '', party_b: '',
    sign_date: '', subject_matter: '', amount: 0, paid_amount: 0, status: '内部审批中',
    owner_name: '', remark: '', is_framework: false, parent_id: null,
  })
}

function openNew() {
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(row: Dict) {
  editingId.value = row.id
  Object.assign(form, {
    contract_no: row.contract_no, name: row.name, type: row.type,
    party_a: row.party_a, party_b: row.party_b,
    sign_date: row.sign_date ?? '', subject_matter: row.subject_matter ?? '',
    amount: row.amount ?? 0, paid_amount: row.paid_amount ?? 0,
    status: row.status, owner_name: row.owner_name ?? '',
    remark: row.remark ?? '', is_framework: row.is_framework,
    parent_id: row.parent_id ?? null,
  })
  dialogVisible.value = true
}

async function save() {
  if (!form.contract_no || !form.name) {
    ElMessage.warning('合同编号与合同名称为必填')
    return
  }
  saving.value = true
  try {
    const payload = { ...form, sign_date: form.sign_date || null }
    if (editingId.value) await updateContract(editingId.value, payload)
    else await createContract(payload)
    ElMessage.success(editingId.value ? '已保存' : '已新增合同')
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

// ---------- 停用/恢复（AC-10/AC-15） ----------
async function remove(row: Dict) {
  try {
    const { value } = await ElMessageBox.prompt(`停用合同「${row.name}」，请输入原因（必填）：`, '停用确认', {
      confirmButtonText: '停用', cancelButtonText: '取消', inputValidator: (v: string) => (v && v.trim() ? true : '原因必填'),
    })
    await softDeleteContract(row.id, value.trim())
    ElMessage.success('已停用（30 天内可恢复）')
    load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') throw e
  }
}

async function restore(row: Dict) {
  try {
    await ElMessageBox.confirm(`恢复合同「${row.name}」？`, '恢复确认', { type: 'warning' })
    await restoreContract(row.id)
    ElMessage.success('已恢复')
    load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') throw e
  }
}

// ---------- 详情（AC-01：详情可打开） ----------
const drawerVisible = ref(false)
const detail = ref<Dict>({})
const logs = ref<Dict[]>([])

async function view(row: Dict) {
  detail.value = await fetchContract(row.id)
  logs.value = await fetchLogs(row.id)
  drawerVisible.value = true
}

function fmtDate(s: string | null | undefined): string {
  return s ? String(s).slice(0, 10) : '—'
}

function fmtMoney(v: any): string {
  return v === null || v === undefined ? '—' : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2 })
}

onMounted(async () => {
  meta.value = await getMeta()
  await Promise.all([load(), loadFrameworks()])
})
</script>

<template>
  <div>
    <!-- 搜索区（完整组合筛选在 T5） -->
    <el-card shadow="never" class="mb">
      <el-form inline>
        <el-form-item label="关键词">
          <el-input v-model="query.keyword" placeholder="编号/名称/甲乙方" clearable style="width: 220px" @keyup.enter="page = 1; load()" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="query.type" clearable placeholder="全部" style="width: 120px">
            <el-option v-for="t in meta.contract_types" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="query.status" clearable placeholder="全部" style="width: 150px">
            <el-option v-for="s in meta.statuses" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="page = 1; load()">查询</el-button>
          <el-button @click="Object.assign(query, { keyword: '', type: '', status: '' }); load()">重置</el-button>
        </el-form-item>
        <el-form-item style="float: right">
          <el-checkbox v-model="query.include_deleted" label="显示已停用" @change="page = 1; load()" />
          <el-button type="success" @click="openNew()">＋ 新增合同</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 表格 -->
    <el-card shadow="never">
      <el-table v-loading="loading" :data="rows" border stripe @row-dblclick="view">
        <el-table-column prop="contract_no" label="合同编号" width="130" />
        <el-table-column prop="name" label="合同名称" min-width="180" show-overflow-tooltip />
        <el-table-column prop="type" label="类型" width="70" />
        <el-table-column prop="party_a" label="甲方" min-width="120" show-overflow-tooltip />
        <el-table-column prop="party_b" label="乙方" min-width="120" show-overflow-tooltip />
        <el-table-column label="金额" width="110" align="right">
          <template #default="{ row }">{{ fmtMoney(row.amount) }}</template>
        </el-table-column>
        <el-table-column label="已付" width="100" align="right">
          <template #default="{ row }">{{ fmtMoney(row.paid_amount) }}</template>
        </el-table-column>
        <el-table-column label="付款比例" width="90" align="right">
          <template #default="{ row }">
            <span v-if="row.payment_ratio !== null">{{ Number(row.payment_ratio).toFixed(1) }}%</span>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="标签" width="150">
          <template #default="{ row }">
            <el-tag v-for="t in row.tags" :key="t" size="small" class="mr-4">{{ t }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="110" />
        <el-table-column prop="owner_name" label="经办人" width="80" />
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="view(row)">详情</el-button>
            <template v-if="row.deleted">
              <el-button link type="success" @click="restore(row)">恢复</el-button>
            </template>
            <template v-else>
              <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
              <el-button link type="danger" @click="remove(row)">停用</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        class="mt"
        @current-change="load"
      />
    </el-card>

    <!-- 新增/编辑弹窗 -->
    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑合同' : '新增合同'" width="720px" destroy-on-close>
      <el-form :model="form" label-width="90px">
        <el-divider content-position="left">基本信息</el-divider>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="合同编号" required><el-input v-model="form.contract_no" placeholder="如 CG-2025-001" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="合同名称" required><el-input v-model="form.name" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="类型"><el-select v-model="form.type" style="width: 100%"><el-option v-for="t in meta.contract_types" :key="t" :label="t" :value="t" /></el-select></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="签订日期"><el-date-picker v-model="form.sign_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="经办人"><el-input v-model="form.owner_name" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="甲方"><el-input v-model="form.party_a" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="乙方"><el-input v-model="form.party_b" /></el-form-item></el-col>
          <el-col :span="24"><el-form-item label="标的物"><el-input v-model="form.subject_matter" type="textarea" :rows="2" /></el-form-item></el-col>
        </el-row>
        <el-divider content-position="left">金额与付款（比例 = 已付 ÷ 金额）</el-divider>
        <el-row :gutter="12">
          <el-col :span="8"><el-form-item label="合同金额"><el-input-number v-model="form.amount" :min="0" :precision="2" :controls="false" style="width: 100%" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="累计已付"><el-input-number v-model="form.paid_amount" :min="0" :precision="2" :controls="false" style="width: 100%" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="状态"><el-select v-model="form.status" style="width: 100%"><el-option v-for="s in meta.statuses" :key="s" :label="s" :value="s" /></el-select></el-form-item></el-col>
        </el-row>
        <el-divider content-position="left">框架与备注</el-divider>
        <el-row :gutter="12">
          <el-col :span="8"><el-form-item label="框架合同"><el-switch v-model="form.is_framework" active-text="是" inactive-text="否" /></el-form-item></el-col>
          <el-col :span="16">
            <el-form-item v-if="!form.is_framework" label="所属框架">
              <el-select v-model="form.parent_id" clearable placeholder="无（独立合同）" style="width: 100%">
                <el-option v-for="f in frameworks" :key="f.id" :label="`${f.contract_no} · ${f.name}`" :value="f.id" />
              </el-select>
            </el-form-item>
            <el-form-item v-else label="说明"><span class="gray">作为框架合同：其他合同可挂到其下（BR6）</span></el-form-item>
          </el-col>
          <el-col :span="24"><el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="2" /></el-form-item></el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 详情抽屉 -->
    <el-drawer v-model="drawerVisible" :title="`合同详情 · ${detail.contract_no ?? ''}`" size="640px">
      <template v-if="detail.id">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="合同名称" :span="2">{{ detail.name }}</el-descriptions-item>
          <el-descriptions-item label="类型">{{ detail.type }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ detail.status }}</el-descriptions-item>
          <el-descriptions-item label="甲方">{{ detail.party_a || '—' }}</el-descriptions-item>
          <el-descriptions-item label="乙方">{{ detail.party_b || '—' }}</el-descriptions-item>
          <el-descriptions-item label="签订日期">{{ fmtDate(detail.sign_date) }}</el-descriptions-item>
          <el-descriptions-item label="经办人">{{ detail.owner_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="标的物" :span="2">{{ detail.subject_matter || '—' }}</el-descriptions-item>
          <el-descriptions-item label="合同金额">{{ fmtMoney(detail.amount) }}</el-descriptions-item>
          <el-descriptions-item label="累计已付">{{ fmtMoney(detail.paid_amount) }}</el-descriptions-item>
          <el-descriptions-item label="付款比例">
            {{ detail.payment_ratio !== null ? Number(detail.payment_ratio).toFixed(1) + '%' : '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="所属框架">{{ detail.parent_no || '—' }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.is_framework" label="子合同" :span="2">
            共 {{ detail.children_count }} 份，金额合计 {{ fmtMoney(detail.children_amount_sum) }}
          </el-descriptions-item>
          <el-descriptions-item label="标签" :span="2">
            <el-tag v-for="t in detail.tags" :key="t" size="small" class="mr-4">{{ t }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.has_warranty" label="质保" :span="2">
            金额 {{ fmtMoney(detail.warranty_amount) }}（{{ detail.warranty_rate }}%）· 到期 {{ fmtDate(detail.warranty_end) }}
          </el-descriptions-item>
        </el-descriptions>

        <el-divider content-position="left">变更历史（时间 · 字段 · 旧值 → 新值）</el-divider>
        <el-timeline v-if="logs.length">
          <el-timeline-item v-for="lg in logs" :key="lg.id" :timestamp="fmtDate(lg.created_at) + ' ' + (lg.created_at || '').slice(11, 19)" placement="top">
            <div v-if="lg.field_name === '_summary' && !lg.new_value"><b>新增合同</b></div>
            <div v-else-if="lg.field_name === 'deleted'"><b>停用/恢复</b>：{{ lg.note }}</div>
            <div v-else>
              <b>{{ lg.field_name }}</b>：{{ lg.old_value ?? '（空）' }} → {{ lg.new_value ?? '（空）' }}
            </div>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="暂无变更记录" :image-size="60" />
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.mb { margin-bottom: 12px; }
.mt { margin-top: 12px; }
.mr-4 { margin-right: 4px; }
.gray { color: #909399; font-size: 13px; }
</style>
