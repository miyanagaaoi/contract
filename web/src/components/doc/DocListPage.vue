<script setup lang="ts">
/**
 * 通用单据列表壳（V2.0，T-V2-24）。
 *
 * 7 类单据（采购申请单 / 采购单 / 销售申请单 / 销售订单 / 入库单 / 出库单 / 盘点单）
 * 列表结构一致，差异只在「往来单位 / 仓库 / 类型」列与权限点，故用配置驱动：
 *
 * - 筛选区：关键词、状态、日期区间、关联合同、（可选）仓库 / 供应商 / 客户；
 * - 表格：单号 / 日期 / 状态 / 往来单位或仓库 / 金额 / 经办人 / 关联合同 + 行内动作；
 * - 行内动作按 `auth.hasPerm()` 与单据状态共同决定，后端仍强制校验（AC-V2-41）；
 * - 作废单据默认不展示，提供「含作废」开关（AC-V2-17）。
 *
 * 详情抽屉通过 `#detail-extra` 插槽交给各页面补充特有字段，本组件只负责表头与行项。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import ApproveDialog from '@/components/doc/ApproveDialog.vue'
import type { ApproveMode } from '@/components/doc/ApproveDialog.vue'
import DocItemsTable from '@/components/doc/DocItemsTable.vue'
import DocStatusTag from '@/components/doc/DocStatusTag.vue'
import {
  docAction,
  exportDoc,
  fetchDoc,
  fetchDocChangelogs,
  fetchDocList,
  fetchMasterOptions,
  fetchPurchaseContractOptions,
  fetchSalesContractOptions,
  openDocPrint,
  type Dict,
} from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { DocChangeLog, DocListQuery, DocRecord } from '@/types/doc'

const props = withDefaults(defineProps<{
  /** 页面标题 */
  title: string
  subtitle?: string
  /** 列表接口前缀，如 '/api/purchase/requests' */
  api: string
  /** 表单页路由名（用于跳转新增/编辑） */
  formRoute: string
  /** 编辑页路由名（缺省用 formRoute）；带 `:id` 的路由必须显式传入，否则 id 会被丢弃 */
  editRoute?: string
  /** 列表路由名（下推后返回列表用） */
  listRoute?: string
  /** 详情/表单页路由名（用于查看） */
  detailRoute?: string
  /** 权限点前缀，如 'purchase.request' */
  permPrefix: string
  /** 新增权限点（缺省为 `${permPrefix}.create`） */
  createPerm?: string
  /** 是否显示仓库列 / 筛选项 */
  showWarehouse?: boolean
  /** 是否显示供应商列 / 筛选项 */
  showSupplier?: boolean
  /** 是否显示客户列 / 筛选项 */
  showCustomer?: boolean
  /** 是否允许下推（显示「下推」按钮） */
  pushable?: boolean
  /** 下推权限点 */
  pushPerm?: string
  /** 行项额外只读列（下推进度等） */
  extraCols?: ('ordered' | 'received' | 'shipped' | 'book' | 'actual' | 'diff')[]
  /** 单据类型标签（详情抽屉标题用） */
  kindLabel?: string
  /** 导出接口路径（如 '/api/sales/orders/export.xlsx'）；设置后显示「导出」按钮 */
  exportPath?: string
  /** 打印接口前缀（缺省与 api 相同），最终请求 `{printApi}/{id}/print` */
  printApi?: string
  /** 是否显示「打印」按钮（单据已保存即可打印） */
  printable?: boolean
  /** 关联合同下拉的数据源：采购方向 / 销售方向 */
  contractSource?: 'purchase' | 'sales'
}>(), {
  subtitle: '',
  listRoute: '',
  detailRoute: '',
  editRoute: '',
  createPerm: '',
  showWarehouse: false,
  showSupplier: false,
  showCustomer: false,
  pushable: false,
  pushPerm: '',
  extraCols: () => [],
  kindLabel: '单据',
  exportPath: '',
  printApi: '',
  printable: true,
  contractSource: 'purchase',
})

const emit = defineEmits<{
  /** 点击「下推」，由各页面打开自己的下推弹窗 */
  push: [row: DocRecord]
  /** 点击「查看」，父页面可自行打开抽屉（未监听时用内置抽屉） */
  view: [row: DocRecord]
}>()

const auth = useAuthStore()
const router = useRouter()

const rows = ref<DocRecord[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const statusOptions = ref<{ code: string; label: string }[]>([])

const query = reactive<Dict>({
  keyword: '',
  status: '',
  date_range: [] as string[],
  include_voided: false,
  contract_id: null,
  warehouse_id: null,
  supplier_id: null,
  customer_id: null,
})

const warehouseOptions = ref<Dict[]>([])
const supplierOptions = ref<Dict[]>([])
const customerOptions = ref<Dict[]>([])
const contractOptions = ref<Dict[]>([])

const canCreate = computed(() => auth.hasPerm(props.createPerm || `${props.permPrefix}.create`))
const canExport = computed(() => !!props.exportPath && auth.hasPerm(`${props.permPrefix}.export`))

/** 权限判定：按钮显示只是体验，后端仍是硬边界 */
function can(code: string): boolean {
  return auth.hasPerm(`${props.permPrefix}.${code}`)
}

/** 列表筛选参数（导出必须与列表同口径，AC-V2-40） */
function queryParams(includePage = false): DocListQuery {
  const params: DocListQuery = {
    keyword: query.keyword || undefined,
    status: query.status || undefined,
    date_from: query.date_range?.[0] || undefined,
    date_to: query.date_range?.[1] || undefined,
    include_voided: query.status === 'voided' ? true : query.include_voided,
    contract_id: query.contract_id || undefined,
    warehouse_id: query.warehouse_id || undefined,
    supplier_id: query.supplier_id || undefined,
    customer_id: query.customer_id || undefined,
  }
  if (includePage) {
    params.page = page.value
    params.page_size = pageSize.value
  }
  return params
}

async function load() {
  loading.value = true
  try {
    const data = await fetchDocList(props.api, queryParams(true))
    rows.value = data.items ?? []
    total.value = data.total ?? rows.value.length
    statusOptions.value = data.statuses ?? []
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function resetQuery() {
  query.keyword = ''
  query.status = ''
  query.date_range = []
  query.include_voided = false
  query.contract_id = null
  query.warehouse_id = null
  query.supplier_id = null
  query.customer_id = null
  page.value = 1
  load()
}

function openNew() {
  router.push({ name: props.formRoute })
}

function openEdit(row: DocRecord) {
  router.push({ name: props.editRoute || props.formRoute, params: { id: String(row.id) } })
}

function openDetail(row: DocRecord) {
  emit('view', row)
  loadDetail(row.id).then(() => { drawerVisible.value = true })
  loadLogs(row.id)
}

// ---------------- 导出 / 打印 ----------------
const exporting = ref(false)

/** 导出当前筛选结果（令牌在请求头，必须走 blob 下载） */
async function doExport() {
  if (!props.exportPath) return
  exporting.value = true
  try {
    await exportDoc(props.exportPath, queryParams(), `${props.kindLabel}导出.xlsx`)
    ElMessage.success('已开始下载')
  } catch {
    // 拦截器已提示
  } finally {
    exporting.value = false
  }
}

/** 打印单据（后端返回可打印 HTML，新窗口打开后由用户点「打印」） */
async function doPrint(row: DocRecord) {
  try {
    await openDocPrint(`${props.printApi || props.api}/${row.id}/print`)
  } catch {
    // 拦截器已提示
  }
}

// ---------------- 内置详情抽屉 ----------------
const drawerVisible = ref(false)
const detail = ref<DocRecord | null>(null)
const detailLoading = ref(false)
const logs = ref<DocChangeLog[]>([])

async function loadDetail(id: number) {
  detailLoading.value = true
  try {
    detail.value = await fetchDoc(props.api, id)
  } catch {
    // 拦截器已提示
  } finally {
    detailLoading.value = false
  }
}

async function loadLogs(id: number) {
  try {
    logs.value = await fetchDocChangelogs(props.api, id)
  } catch {
    logs.value = []
  }
}

function fmtMoney(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  return Number.isNaN(n) ? String(v) : n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtDate(v: unknown): string {
  return v ? String(v).slice(0, 10) : '—'
}

/** 往来单位 / 仓库列取值（销售申请单可能只填了客户文本） */
function partyOf(row: DocRecord): string {
  if (props.showSupplier) return row.supplier_name || '—'
  if (props.showCustomer) return row.customer_name || (row.customer_name_text as string) || '—'
  if (props.showWarehouse) return row.warehouse_name || '—'
  return '—'
}

function partyLabel(): string {
  if (props.showSupplier) return '供应商'
  if (props.showCustomer) return '客户'
  if (props.showWarehouse) return '仓库'
  return '往来单位'
}

// ---------------- 行内动作 ----------------
const actionLoading = ref(false)
const approveVisible = ref(false)
const approveMode = ref<ApproveMode>('approve')
const actionRow = ref<DocRecord | null>(null)

async function doSimple(row: DocRecord, action: 'submit' | 'approve' | 'complete') {
  const label = action === 'submit' ? '提交' : action === 'approve' ? '审核' : '完成'
  actionLoading.value = true
  try {
    await docAction(props.api, row.id, action)
    ElMessage.success(`${label}成功`)
    await load()
  } catch {
    // 422（如"不能审核自己创建的单据"）由拦截器提示
  } finally {
    actionLoading.value = false
  }
}

function openApprove(row: DocRecord, mode: ApproveMode) {
  actionRow.value = row
  approveMode.value = mode
  approveVisible.value = true
}

async function onApproveConfirm({ mode, reason }: { mode: ApproveMode; reason: string }) {
  if (!actionRow.value) return
  actionLoading.value = true
  try {
    await docAction(props.api, actionRow.value.id, mode, mode === 'approve' ? {} : { reason })
    ElMessage.success('操作成功')
    approveVisible.value = false
    await load()
  } catch {
    // 拦截器已提示
  } finally {
    actionLoading.value = false
  }
}

/** 状态 → 可执行动作（与后端状态机一致） */
function canSubmit(row: DocRecord): boolean { return row.status === 'draft' && can('submit') }
function canApprove(row: DocRecord): boolean { return row.status === 'submitted' && can('approve') }
function canReject(row: DocRecord): boolean { return row.status === 'submitted' && can('approve') }
function canVoid(row: DocRecord): boolean {
  return (row.status === 'draft' || row.status === 'submitted') && can('void')
}
function canUnapprove(row: DocRecord): boolean {
  return (row.status === 'approved' || row.status === 'completed') && can('approve')
}
function canEdit(row: DocRecord): boolean { return !!row.editable && can('edit') }
function canPush(row: DocRecord): boolean {
  return props.pushable && auth.hasPerm(props.pushPerm || `${props.permPrefix}.push`)
    && (row.status === 'approved' || row.status === 'completed')
}

async function loadOptions() {
  try {
    if (props.showWarehouse) warehouseOptions.value = await fetchMasterOptions('warehouse')
    if (props.showSupplier) supplierOptions.value = await fetchMasterOptions('supplier')
    if (props.showCustomer) customerOptions.value = await fetchMasterOptions('customer')
  } catch {
    // 下拉失败不阻塞列表
  }
  try {
    contractOptions.value = props.contractSource === 'sales'
      ? await fetchSalesContractOptions()
      : await fetchPurchaseContractOptions()
  } catch {
    contractOptions.value = []
  }
}

onMounted(async () => {
  await Promise.all([loadOptions(), load()])
})

defineExpose({ load, rows })
</script>

<template>
  <div>
    <el-card shadow="never" class="mb">
      <template #header>
        <div class="head">
          <div>
            <span class="title">{{ title }}</span>
            <span v-if="subtitle" class="subtitle">{{ subtitle }}</span>
          </div>
          <div>
            <el-button v-if="canExport" :loading="exporting" @click="doExport">
              <el-icon><Download /></el-icon>导出
            </el-button>
            <el-button v-if="canCreate" type="primary" @click="openNew">
              <el-icon><Plus /></el-icon>新增
            </el-button>
          </div>
        </div>
      </template>

      <el-form inline>
        <el-form-item label="关键词">
          <el-input v-model="query.keyword" placeholder="单号 / 来源单号 / 合同号 / 往来单位"
                    clearable style="width: 220px" @keyup.enter="page = 1; load()" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="query.status" clearable style="width: 130px" @change="page = 1; load()">
            <el-option v-for="s in statusOptions" :key="s.code" :label="s.label" :value="s.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="单据日期">
          <el-date-picker v-model="query.date_range" type="daterange" value-format="YYYY-MM-DD"
                          start-placeholder="开始" end-placeholder="结束" style="width: 240px"
                          @change="page = 1; load()" />
        </el-form-item>
        <el-form-item v-if="showWarehouse" label="仓库">
          <el-select v-model="query.warehouse_id" clearable filterable style="width: 160px"
                     @change="page = 1; load()">
            <el-option v-for="w in warehouseOptions" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="showSupplier" label="供应商">
          <el-select v-model="query.supplier_id" clearable filterable style="width: 170px"
                     @change="page = 1; load()">
            <el-option v-for="s in supplierOptions" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="showCustomer" label="客户">
          <el-select v-model="query.customer_id" clearable filterable style="width: 170px"
                     @change="page = 1; load()">
            <el-option v-for="c in customerOptions" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="关联合同">
          <el-select v-model="query.contract_id" clearable filterable style="width: 200px"
                     :placeholder="contractSource === 'sales' ? '选择销售合同' : '选择采购合同'"
                     @change="page = 1; load()">
            <el-option v-for="c in contractOptions" :key="c.id"
                       :label="`${c.contract_no} · ${c.name}`" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="含作废">
          <el-switch v-model="query.include_voided" @change="page = 1; load()" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="page = 1; load()">查询</el-button>
          <el-button @click="resetQuery">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="rows" border stripe size="small">
        <el-table-column type="index" label="#" width="52" />
        <el-table-column prop="doc_no" label="单号" width="170" show-overflow-tooltip>
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">{{ row.doc_no }}</el-button>
          </template>
        </el-table-column>
        <el-table-column label="单据日期" width="110">
          <template #default="{ row }">{{ fmtDate(row.doc_date) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="94">
          <template #default="{ row }">
            <DocStatusTag :status="row.status" :label="row.status_label" />
          </template>
        </el-table-column>
        <el-table-column :label="partyLabel()" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ partyOf(row) }}</template>
        </el-table-column>
        <el-table-column label="金额" width="120" align="right">
          <template #default="{ row }">{{ fmtMoney(row.total_amount) }}</template>
        </el-table-column>
        <el-table-column label="经办人" width="90">
          <template #default="{ row }">{{ row.created_by_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="关联合同" width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.contract_no || '—' }}</template>
        </el-table-column>
        <el-table-column label="来源单号" width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.source_doc_no || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openDetail(row)">查看</el-button>
            <el-button v-if="canEdit(row)" link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button v-if="canSubmit(row)" link type="success" size="small"
                       :loading="actionLoading" @click="doSimple(row, 'submit')">提交</el-button>
            <el-button v-if="canApprove(row)" link type="primary" size="small"
                       @click="openApprove(row, 'approve')">审核</el-button>
            <el-button v-if="canReject(row)" link type="warning" size="small"
                       @click="openApprove(row, 'reject')">驳回</el-button>
            <el-button v-if="canPush(row)" link type="primary" size="small"
                       @click="emit('push', row)">下推</el-button>
            <el-button v-if="printable" link type="info" size="small" @click="doPrint(row)">打印</el-button>
            <el-button v-if="canUnapprove(row)" link type="warning" size="small"
                       @click="openApprove(row, 'unapprove')">反审核</el-button>
            <el-button v-if="canVoid(row)" link type="danger" size="small"
                       @click="openApprove(row, 'void')">作废</el-button>
          </template>
        </el-table-column>
        <template #empty>暂无数据</template>
      </el-table>

      <el-pagination v-if="total > pageSize" class="pager" background
                     layout="total, prev, pager, next, sizes" :total="total"
                     :current-page="page" :page-size="pageSize" :page-sizes="[10, 20, 50, 100]"
                     @current-change="(p: number) => { page = p; load() }"
                     @size-change="(s: number) => { pageSize = s; page = 1; load() }" />
    </el-card>

    <!-- 详情抽屉（通用部分；特有字段由页面用 #detail-extra 插槽补充） -->
    <el-drawer v-model="drawerVisible" :title="`${kindLabel}详情 · ${detail?.doc_no ?? ''}`" size="720px">
      <div v-if="detail" v-loading="detailLoading">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="单号">{{ detail.doc_no }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <DocStatusTag :status="detail.status" :label="detail.status_label" />
          </el-descriptions-item>
          <el-descriptions-item label="单据日期">{{ fmtDate(detail.doc_date) }}</el-descriptions-item>
          <el-descriptions-item label="经办人">{{ detail.created_by_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="关联合同">{{ detail.contract_no || '—' }}</el-descriptions-item>
          <el-descriptions-item label="来源单号">{{ detail.source_doc_no || '—' }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.supplier_name" label="供应商">{{ detail.supplier_name }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.customer_name" label="客户">{{ detail.customer_name }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.warehouse_name" label="仓库">{{ detail.warehouse_name }}</el-descriptions-item>
          <el-descriptions-item label="总金额">{{ fmtMoney(detail.total_amount) }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.posted" label="库存过账" :span="2">
            <el-tag type="success" size="small">已过账</el-tag>
            <span class="gray">（审核即过账，反审核会红冲）</span>
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.void_reason" label="作废原因" :span="2">{{ detail.void_reason }}</el-descriptions-item>
          <slot name="detail-head" :detail="detail" />
          <el-descriptions-item label="备注" :span="2">{{ detail.remark || '—' }}</el-descriptions-item>
        </el-descriptions>

        <slot name="detail-extra" :detail="detail" />

        <div v-if="printable" class="drawer-actions">
          <el-button size="small" @click="doPrint(detail)">
            <el-icon><Printer /></el-icon>打印单据
          </el-button>
        </div>

        <el-divider content-position="left">行项明细</el-divider>
        <DocItemsTable :items="(detail.items || []) as unknown as Record<string, any>[]" readonly
                       :show-warehouse="showWarehouse" :extra-cols="extraCols" />

        <el-divider content-position="left">变更历史</el-divider>
        <el-timeline v-if="logs.length">
          <el-timeline-item v-for="(lg, i) in logs" :key="lg.id ?? i"
                            :timestamp="`${fmtDate(lg.created_at)} ${(lg.created_at || '').slice(11, 19)}`" placement="top">
            <div><b>{{ lg.field_name }}</b>：{{ lg.old_value ?? '（空）' }} → {{ lg.new_value ?? '（空）' }}</div>
            <div v-if="lg.note" class="gray">{{ lg.note }}</div>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="暂无变更记录" :image-size="60" />
      </div>
    </el-drawer>

    <ApproveDialog v-model="approveVisible" :mode="approveMode" :loading="actionLoading"
                   :subject="`${kindLabel} ${actionRow?.doc_no ?? ''}`" @confirm="onApproveConfirm" />
  </div>
</template>

<style scoped>
.mb { margin-bottom: 12px; }
.head { display: flex; align-items: center; justify-content: space-between; }
.title { font-weight: 600; font-size: 15px; }
.subtitle { margin-left: 10px; color: #909399; font-size: 12.5px; }
.pager { margin-top: 12px; justify-content: flex-end; }
.drawer-actions { margin-top: 12px; display: flex; gap: 8px; }
.gray { color: #909399; font-size: 12.5px; }
</style>
