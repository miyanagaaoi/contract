<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  attachmentUrl,
  canPreview,
  createContract,
  createTag,
  deleteAttachment,
  deleteTag,
  fetchAttachments,
  fetchContract,
  fetchContracts,
  fetchLogs,
  fetchTags,
  getMeta,
  renameTag,
  restoreContract,
  softDeleteContract,
  updateContract,
  uploadAttachment,
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
const tagOptions = ref<Dict[]>([])

const query = reactive<Dict>({
  keyword: '',
  type: '',
  status: '',
  owner: '',
  tags: [] as string[],
  date_range: [] as string[],
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
    if (query.owner) params.owner = query.owner
    if (query.tags.length) params.tags = query.tags.join(',')
    if (query.date_range.length === 2) {
      params.sign_from = query.date_range[0]
      params.sign_to = query.date_range[1]
    }
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

async function loadTags() {
  tagOptions.value = await fetchTags()
}

// ---------- 新增/编辑 ----------
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const form = reactive<Dict>({
  contract_no: '', name: '', type: '采购', party_a: '', party_b: '',
  sign_date: '', subject_matter: '', amount: 0, paid_amount: 0, status: '内部审批中',
  owner_name: '', remark: '', is_framework: false, parent_id: null, tags: [],
})

function resetForm() {
  Object.assign(form, {
    contract_no: '', name: '', type: '采购', party_a: '', party_b: '',
    sign_date: '', subject_matter: '', amount: 0, paid_amount: 0, status: '内部审批中',
    owner_name: '', remark: '', is_framework: false, parent_id: null, tags: [],
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
    parent_id: row.parent_id ?? null, tags: [...(row.tags ?? [])],
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

// ---------- 标签管理（T4，AC-13） ----------
const tagDialogVisible = ref(false)
const newTagName = ref('')

function apiError(e: any): string {
  return e?.response?.data?.detail || '操作失败'
}

async function addTag() {
  const name = newTagName.value.trim()
  if (!name) return
  try {
    await createTag(name)
    ElMessage.success('标签已新增')
    newTagName.value = ''
    await loadTags()
  } catch (e) {
    ElMessage.error(apiError(e))
  }
}

async function tagRename(tag: Dict) {
  try {
    const { value } = await ElMessageBox.prompt('新名称：', `重命名标签「${tag.name}」`, {
      inputValue: tag.name, confirmButtonText: '确定', cancelButtonText: '取消',
    })
    await renameTag(tag.id, value.trim())
    ElMessage.success('已重命名')
    await loadTags()
    load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(apiError(e))
  }
}

async function tagRemove(tag: Dict) {
  try {
    await ElMessageBox.confirm(`删除标签「${tag.name}」？它将从 ${tag.usage_count} 个合同上移除。`, '删除确认', { type: 'warning' })
    await deleteTag(tag.id)
    ElMessage.success('已删除')
    await loadTags()
    load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(apiError(e))
  }
}

// ---------- 详情（AC-01：详情可打开） ----------
const drawerVisible = ref(false)
const detail = ref<Dict>({})
const logs = ref<Dict[]>([])
const atts = ref<Dict[]>([])
const uploading = ref(false)

async function view(row: Dict) {
  detail.value = await fetchContract(row.id)
  logs.value = await fetchLogs(row.id)
  atts.value = await fetchAttachments(row.id)
  drawerVisible.value = true
}

async function onUpload(file: File) {
  if (!detail.value.id) return
  uploading.value = true
  try {
    await uploadAttachment(detail.value.id, file)
    ElMessage.success('上传成功')
    atts.value = await fetchAttachments(detail.value.id)
    logs.value = await fetchLogs(detail.value.id)
  } catch (e) {
    ElMessage.error(apiError(e))
  } finally {
    uploading.value = false
  }
}

async function onDeleteAttachment(row: Dict) {
  try {
    await ElMessageBox.confirm(`删除附件「${row.file_name}」？`, '删除确认', { type: 'warning' })
    await deleteAttachment(detail.value.id, row.id)
    ElMessage.success('已删除')
    atts.value = await fetchAttachments(detail.value.id)
    logs.value = await fetchLogs(detail.value.id)
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(apiError(e))
  }
}

function fmtSize(bytes: number): string {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function openAttachment(row: Dict) {
  if (canPreview(row.file_name)) window.open(attachmentUrl(row.id, true), '_blank')
  else window.open(attachmentUrl(row.id), '_blank')
}

function fmtDate(s: string | null | undefined): string {
  return s ? String(s).slice(0, 10) : '—'
}

function fmtMoney(v: any): string {
  return v === null || v === undefined ? '—' : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2 })
}

// ---------- 状态流转（T6，AC-04） ----------
const statusDlgVisible = ref(false)
const statusRow = ref<Dict>({})
const newStatus = ref('')
const statusNote = ref('')

function openStatus(row: Dict) {
  statusRow.value = row
  newStatus.value = row.status
  statusNote.value = ''
  statusDlgVisible.value = true
}

async function saveStatus() {
  if (!newStatus.value) {
    ElMessage.warning('请选择新状态')
    return
  }
  try {
    const payload: Dict = { status: newStatus.value }
    if (statusNote.value.trim()) payload.note = statusNote.value.trim()
    await updateContract(statusRow.value.id, payload)
    ElMessage.success('状态已更新')
    statusDlgVisible.value = false
    load()
  } catch (e) {
    ElMessage.error(apiError(e))
  }
}

// 变更历史字段中文标签（AC-12 展示友好）
const FIELD_LABELS: Record<string, string> = {
  contract_no: '合同编号', name: '合同名称', type: '类型', party_a: '甲方', party_b: '乙方',
  sign_date: '签订日期', effective_date: '生效日期', subject_matter: '标的物', amount: '合同金额',
  currency: '币种', paid_amount: '累计已付', status: '状态', owner_name: '经办人', remark: '备注',
  is_framework: '框架合同', parent_id: '所属框架', arrival_status: '到货状态',
  expected_arrival_date: '预计到货', has_warranty: '有质保金', warranty_amount: '质保金金额',
  warranty_rate: '质保金比例', warranty_start: '质保生效', warranty_months: '质保期限',
  warranty_end: '质保到期', warranty_released: '质保已释放', warranty_release_date: '释放日期',
  warranty_note: '质保备注', deleted: '删除', _tags: '标签', _summary: '概要',
}

function fLabel(f: string): string {
  return FIELD_LABELS[f] ?? f
}

onMounted(async () => {
  meta.value = await getMeta()
  await Promise.all([load(), loadFrameworks(), loadTags()])
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
        <el-form-item label="经办人">
          <el-input v-model="query.owner" clearable placeholder="经办人" style="width: 100px" @keyup.enter="page = 1; load()" />
        </el-form-item>
        <el-form-item label="标签">
          <el-select v-model="query.tags" multiple collapse-tags collapse-tags-tooltip clearable placeholder="包含全部所选" style="width: 200px">
            <el-option v-for="t in tagOptions" :key="t.id" :label="t.name" :value="String(t.id)" />
          </el-select>
        </el-form-item>
        <el-form-item label="签订日期">
          <el-date-picker v-model="query.date_range" type="daterange" value-format="YYYY-MM-DD"
                          start-placeholder="起" end-placeholder="止" style="width: 240px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="page = 1; load()">查询</el-button>
          <el-button @click="Object.assign(query, { keyword: '', type: '', status: '', tags: [], date_range: [], owner: '' }); load()">重置</el-button>
        </el-form-item>
        <el-form-item style="float: right">
          <el-checkbox v-model="query.include_deleted" label="显示已停用" @change="page = 1; load()" />
          <el-button @click="tagDialogVisible = true">标签管理</el-button>
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
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="view(row)">详情</el-button>
            <template v-if="row.deleted">
              <el-button link type="success" @click="restore(row)">恢复</el-button>
            </template>
            <template v-else>
              <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
              <el-button link type="warning" @click="openStatus(row)">状态</el-button>
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
          <el-col :span="24"><el-form-item label="标签">
            <el-select v-model="form.tags" multiple filterable allow-create default-first-option clearable
                       placeholder="选择已有标签，或输入后回车新建" style="width: 100%">
              <el-option v-for="t in tagOptions" :key="t.id" :label="t.name" :value="t.name" />
            </el-select>
          </el-form-item></el-col>
          <el-col :span="24"><el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="2" /></el-form-item></el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 状态流转（T6，AC-04） -->
    <el-dialog v-model="statusDlgVisible" :title="`状态流转 · ${statusRow.contract_no ?? ''}`" width="460px">
      <el-form label-width="80px">
        <el-form-item label="当前状态"><el-tag>{{ statusRow.status }}</el-tag></el-form-item>
        <el-form-item label="新状态">
          <el-select v-model="newStatus" style="width: 100%">
            <el-option v-for="s in meta.statuses" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注（可选）">
          <el-input v-model="statusNote" type="textarea" :rows="2" placeholder="流转说明/原因" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="statusDlgVisible = false">取消</el-button>
        <el-button type="primary" @click="saveStatus">确认流转</el-button>
      </template>
    </el-dialog>

    <!-- 标签管理（T4，AC-13） -->
    <el-dialog v-model="tagDialogVisible" title="标签管理" width="520px">
      <div class="mb" style="display: flex; gap: 8px">
        <el-input v-model="newTagName" placeholder="新标签名称，回车确认" @keyup.enter="addTag" />
        <el-button type="primary" @click="addTag">新增</el-button>
      </div>
      <el-table :data="tagOptions" size="small" border>
        <el-table-column label="标签" min-width="160">
          <template #default="{ row }">
            <el-tag :color="row.color" style="color:#fff;border:none">{{ row.name }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="usage_count" label="使用合同数" width="100" align="center" />
        <el-table-column label="操作" width="130">
          <template #default="{ row }">
            <el-button link type="primary" @click="tagRename(row)">改名</el-button>
            <el-button link type="danger" @click="tagRemove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
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

        <el-divider content-position="left">附件（T7 · 上传/下载/预览，PDF 与图片可预览）</el-divider>
        <div class="mb">
          <el-upload
            :show-file-list="false"
            :http-request="(o: any) => onUpload(o.file as File)"
            :before-upload="(f: File) => f.size <= 20 * 1024 * 1024 || (ElMessage.error('附件不能超过 20MB'), false)"
            accept=".pdf,.doc,.docx,.xls,.xlsx,.png,.jpg,.jpeg,.gif,.txt"
          >
            <el-button type="primary" :loading="uploading" plain>上传附件</el-button>
          </el-upload>
        </div>
        <el-table v-if="atts.length" :data="atts" size="small" border>
          <el-table-column prop="file_name" label="文件名" min-width="180" show-overflow-tooltip />
          <el-table-column label="大小" width="90">
            <template #default="{ row }">{{ fmtSize(row.size_bytes) }}</template>
          </el-table-column>
          <el-table-column label="上传时间" width="110">
            <template #default="{ row }">{{ fmtDate(row.uploaded_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="150">
            <template #default="{ row }">
              <el-button link type="primary" @click="openAttachment(row)">
                {{ canPreview(row.file_name) ? '预览' : '下载' }}
              </el-button>
              <el-button link type="danger" @click="onDeleteAttachment(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else-if="!uploading" description="暂无附件" :image-size="60" />

        <el-divider content-position="left">变更历史（时间 · 字段 · 旧值 → 新值）</el-divider>
        <el-timeline v-if="logs.length">
          <el-timeline-item v-for="lg in logs" :key="lg.id" :timestamp="fmtDate(lg.created_at) + ' ' + (lg.created_at || '').slice(11, 19)" placement="top">
            <div v-if="lg.field_name === '_summary' && lg.new_value">变更字段：{{ lg.new_value }}</div>
            <div v-else-if="lg.field_name === '_summary'"><b>新增合同</b></div>
            <div v-else-if="lg.field_name === 'deleted'"><b>停用/恢复</b>：{{ lg.note }}</div>
            <div v-else-if="lg.field_name === '备注'"><b>备注</b>：{{ lg.new_value }}</div>
            <div v-else><b>{{ fLabel(lg.field_name) }}</b>：{{ lg.old_value ?? '（空）' }} → {{ lg.new_value ?? '（空）' }}</div>
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
