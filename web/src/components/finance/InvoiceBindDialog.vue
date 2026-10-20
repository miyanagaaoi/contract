<script setup lang="ts">
/**
 * V2.6 采购单「登记进项发票」绑定弹窗（docs/38 §5 / 设计稿 ③）。
 *
 * 由采购单列表「更多 → 登记进项发票」唤起：默认只列「未确认」进项发票，
 * 支持多选绑定；绑定成功后发票 `bind_status → bound`，采购单收票进度按价税合计累计。
 * 已绑定到本采购单的发票也展示出来（禁选），支持在此解绑。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { bindInvoices, fetchDocList, unbindInvoice, type Dict } from '@/api'
import { fmtDate, fmtMoney } from '@/utils/format'
import type { DocRecord } from '@/types/doc'

const props = defineProps<{
  modelValue: boolean
  purchaseOrder: DocRecord | null
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void
                           (e: 'changed'): void }>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const rows = ref<DocRecord[]>([])
const loading = ref(false)
const keyword = ref('')
const selected = ref<DocRecord[]>([])
const binding = ref(false)

const remain = computed(() => {
  const po = props.purchaseOrder as any
  const item = po?.progress?.invoiced_amount
  if (!item) return null
  // V2.5 进度口径：{ num: 已收票, den: 含税单据金额 }（finance_service._item）
  return Number(item.den || 0) - Number(item.num || 0)
})
const selectedTotal = computed(() =>
  selected.value.reduce((sum, r) => sum + Number(r.total_amount || 0), 0))
const overRemain = computed(() =>
  remain.value != null && selectedTotal.value > remain.value)

async function load() {
  if (!props.purchaseOrder) return
  loading.value = true
  try {
    // 未确认（可绑定）+ 已绑定到本单（可解绑）：后端按 bind_status 过滤，两次拉取
    const [unbound, bound] = await Promise.all([
      fetchDocList('/finance/invoices', {
        page: 1, page_size: 100, direction: 'in', bind_status: 'unbound',
        status: 'draft', include_voided: false, is_red: false,
        keyword: keyword.value || undefined,
      }),
      fetchDocList('/finance/invoices', {
        page: 1, page_size: 100, direction: 'in', bind_status: 'bound',
        include_voided: false, keyword: keyword.value || undefined,
      }),
    ])
    const boundRows = ((bound.items || []) as DocRecord[])
      .filter((r) => (r.allocations || []).some(
        (a: Dict) => a.target_type === 'purchase_order'
                     && Number(a.target_id) === Number(props.purchaseOrder?.id)))
      .map((r) => ({ ...r, _mine: true }))
    rows.value = [
      ...boundRows,
      ...((unbound.items || []) as DocRecord[]).map((r) => ({ ...r, _mine: false })),
    ]
  } finally {
    loading.value = false
  }
}

watch(visible, (v) => {
  if (v) { keyword.value = ''; selected.value = []; load() }
})

async function doBind() {
  if (!selected.value.length || !props.purchaseOrder) return
  if (overRemain.value) {
    await ElMessageBox.confirm(
      `勾选价税合计 ${fmtMoney(selectedTotal.value)} 超过采购单未收票余额 `
      + `${fmtMoney(remain.value || 0)}，收票进度将显示超额，确认绑定？`,
      '超额提醒', { type: 'warning', confirmButtonText: '仍要绑定' })
  }
  binding.value = true
  try {
    const res = await bindInvoices(props.purchaseOrder.id,
                                   selected.value.map((r) => r.id))
    const boundCount = (res.bound || []).length
    const failed = (res.errors || []) as Dict[]
    if (failed.length) {
      ElMessage.warning(`绑定 ${boundCount} 张成功，${failed.length} 张失败：`
                        + failed.map((e) => e.reason).join('；'))
    } else {
      ElMessage.success(`已绑定 ${boundCount} 张发票，收票进度已更新`)
    }
    selected.value = []
    emit('changed')
    await load()
  } catch { /* 拦截器已提示 */ } finally {
    binding.value = false
  }
}

async function doUnbind(row: DocRecord) {
  try {
    await ElMessageBox.confirm(
      `解绑发票 ${row.invoice_no}？将删除核销明细并重算收票进度，发票回到「未确认」。`,
      '解绑发票', { type: 'warning', confirmButtonText: '解绑' })
    await unbindInvoice(row.id)
    ElMessage.success('已解绑，收票进度已重算')
    emit('changed')
    await load()
  } catch { /* 取消或后端校验失败 */ }
}

function selectable(row: DocRecord) {
  return !row._mine
}
</script>

<template>
  <el-dialog v-model="visible" width="920px" :close-on-click-modal="false">
    <template #header>
      登记进项发票 — {{ purchaseOrder?.doc_no }}
      <span class="po-hint">{{ purchaseOrder?.supplier_name }}
        含税 {{ fmtMoney(Number(purchaseOrder?.total_amount || 0)) }}</span>
    </template>

    <div class="toolbar">
      <el-select model-value="unbound" disabled style="width: 150px">
        <el-option label="确认状态：未确认" value="unbound" />
      </el-select>
      <el-input v-model="keyword" placeholder="发票号码" clearable style="width: 180px"
                @keyup.enter="load" />
      <el-button @click="load">筛选</el-button>
      <span class="hint">默认仅显示「未确认」发票；绿色行是已绑定到本单的发票（可解绑）</span>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe size="small" height="340"
              @selection-change="(v: DocRecord[]) => selected = v.filter((r) => !r._mine)">
      <el-table-column type="selection" width="40" :selectable="selectable" />
      <el-table-column label="发票号码" width="185" show-overflow-tooltip>
        <template #default="{ row }">{{ row.invoice_no }}</template>
      </el-table-column>
      <el-table-column label="开票日期" width="100">
        <template #default="{ row }">{{ fmtDate(row.invoice_date) }}</template>
      </el-table-column>
      <el-table-column label="开票单位" min-width="170" show-overflow-tooltip>
        <template #default="{ row }">{{ row.seller_name || row.party_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="税率" width="70" align="right">
        <template #default="{ row }">
          {{ row.tax_rate != null ? Number(row.tax_rate) + '%' : '—' }}
        </template>
      </el-table-column>
      <el-table-column label="税额" width="100" align="right">
        <template #default="{ row }">{{ fmtMoney(row.tax_amount || 0) }}</template>
      </el-table-column>
      <el-table-column label="金额" width="110" align="right">
        <template #default="{ row }">{{ fmtMoney(row.amount || 0) }}</template>
      </el-table-column>
      <el-table-column label="价税合计" width="115" align="right">
        <template #default="{ row }">{{ fmtMoney(row.total_amount || 0) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="150">
        <template #default="{ row }">
          <template v-if="row._mine">
            <el-tag type="success" size="small">已确认（本单）</el-tag>
            <el-button link type="danger" size="small" @click="doUnbind(row)">解绑</el-button>
          </template>
          <el-tag v-else type="info" size="small">未确认</el-tag>
        </template>
      </el-table-column>
    </el-table>

    <el-alert v-if="selected.length" :type="overRemain ? 'warning' : 'info'" :closable="false"
              style="margin-top: 12px">
      已选 {{ selected.length }} 张 · 价税合计 <b>{{ fmtMoney(selectedTotal) }}</b>
      <template v-if="remain != null">；采购单未收票余额 <b>{{ fmtMoney(remain) }}</b>
        <template v-if="overRemain">，勾选金额<b>超过余额</b>，进度将显示超额</template>
      </template>
    </el-alert>

    <template #footer>
      <span class="footer-hint">绑定后发票状态 → 已确认；可在发票详情解绑并自动重算进度</span>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :disabled="!selected.length" :loading="binding" @click="doBind">
        确认绑定（{{ selected.length }}）
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.po-hint { color: var(--el-text-color-secondary); font-size: 13px; font-weight: 400; margin-left: 10px }
.toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 12px }
.hint { color: var(--el-text-color-secondary); font-size: 12px }
.footer-hint { color: var(--el-text-color-secondary); font-size: 12px; margin-right: auto }
</style>
