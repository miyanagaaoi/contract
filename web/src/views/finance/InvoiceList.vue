<script setup lang="ts">
/**
 * 发票管理（V2.5，AC-V2.5-09~11）。
 *
 * 进项/销项同表：列表按 `direction` 分页签（用「方向」筛选项切换），
 * 认证状态（待认证/已认证）由财务手工流转，**不影响**收票/开票进度；
 * 「确认入账」才是记账动作（回写目标单据的 `invoiced_amount`）。
 *
 * 发票的状态机与普通单据不同（草稿 → 已确认 → 已作废，没有提交/审核），因此
 * 「确认入账」「标记认证」「作废（已确认的先红冲）」都放在「更多」里由本页处理。
 */
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import DocListPage from '@/components/doc/DocListPage.vue'
import { confirmInvoice, voidInvoice, verifyInvoice, type Dict } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { fmtDate, fmtMoney } from '@/utils/format'
import type { DocRecord } from '@/types/doc'

const auth = useAuthStore()
const listRef = ref<InstanceType<typeof DocListPage> | null>(null)
const direction = ref<string>('in')
const authStatus = ref<string>('')

const filterParams = computed<Dict>(() => ({
  direction: direction.value || undefined,
  auth_status: authStatus.value || undefined,
}))

const canConfirm = computed(() => auth.hasPerm('finance.invoice.confirm'))
const canVoid = computed(() => auth.hasPerm('finance.invoice.void'))

function flash(message: string) {
  ElMessage.success(message)
  listRef.value?.load()
}

async function onMore({ command, row }: { command: string; row: DocRecord }) {
  try {
    if (command === 'invoice-confirm') {
      await ElMessageBox.confirm(
        `确认发票 ${row.invoice_no} 入账？确认后计入对应单据的收票/开票进度（含税口径）。`,
        '确认入账', { type: 'info', confirmButtonText: '确认入账', cancelButtonText: '取消' })
      await confirmInvoice(row.id)
      flash('已确认入账')
      return
    }
    if (command === 'invoice-verify' || command === 'invoice-unverify') {
      const next = command === 'invoice-verify' ? 'verified' : 'pending'
      await verifyInvoice(row.id, next)
      flash(next === 'verified' ? '已标记为已认证' : '已退回待认证')
      return
    }
    if (command === 'invoice-void') {
      const { value } = await ElMessageBox.prompt('作废原因（必填）', '作废发票', {
        type: 'warning', confirmButtonText: '确定作废', cancelButtonText: '取消',
        inputValidator: (v: string) => (v && v.trim() ? true : '请填写作废原因'),
      })
      await voidInvoice(row.id, value)
      flash('发票已作废（已确认的已红冲）')
    }
  } catch {
    // 取消或后端校验失败（拦截器已提示）
  }
}
</script>

<template>
  <DocListPage ref="listRef" title="发票管理" api="/api/finance/invoices"
               subtitle="进项/销项发票登记与认证；确认入账后计入收票/开票进度（含税口径）"
               perm-prefix="finance.invoice" kind-label="发票"
               form-route="finance-invoice-form" edit-route="finance-invoice-edit"
               detail-route="finance-invoice-detail" show-subject
               :extra-filter-params="filterParams"
               export-path="/api/finance/invoices/export.xlsx" @more="onMore">
    <template #extra-filters="{ reload }">
      <el-form-item label="方向">
        <el-select v-model="direction" style="width: 120px" @change="reload">
          <el-option label="进项发票" value="in" />
          <el-option label="销项发票" value="out" />
        </el-select>
      </el-form-item>
      <el-form-item label="认证">
        <el-select v-model="authStatus" clearable style="width: 120px" placeholder="全部"
                   @change="reload">
          <el-option label="待认证" value="pending" />
          <el-option label="已认证" value="verified" />
        </el-select>
      </el-form-item>
    </template>

    <template #extra-columns>
      <el-table-column label="发票号码" width="150" show-overflow-tooltip>
        <template #default="{ row }">{{ row.invoice_no }}</template>
      </el-table-column>
      <el-table-column label="票种" width="140" show-overflow-tooltip>
        <template #default="{ row }">{{ row.invoice_type || '—' }}</template>
      </el-table-column>
      <el-table-column label="认证" width="90">
        <template #default="{ row }">
          <el-tag :type="row.auth_status === 'verified' ? 'success' : 'info'" size="small">
            {{ row.auth_status_label || row.auth_status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="不含税" width="110" align="right">
        <template #default="{ row }">{{ fmtMoney(row.amount || 0) }}</template>
      </el-table-column>
      <el-table-column label="税额" width="100" align="right">
        <template #default="{ row }">{{ fmtMoney(row.tax_amount || 0) }}</template>
      </el-table-column>
    </template>

    <!-- 「更多」里的发票动作：确认入账 / 认证状态 / 作废（命令由本页 onMore 处理） -->
    <template #more-actions="{ row }">
      <el-dropdown-item v-if="canConfirm && row.status === 'draft'" divided
                        command="invoice-confirm">确认入账</el-dropdown-item>
      <el-dropdown-item v-if="canConfirm && row.status !== 'voided'
                              && row.auth_status !== 'verified'"
                        command="invoice-verify">标记已认证</el-dropdown-item>
      <el-dropdown-item v-if="canConfirm && row.status !== 'voided'
                              && row.auth_status === 'verified'"
                        command="invoice-unverify">退回待认证</el-dropdown-item>
      <el-dropdown-item v-if="canVoid && row.status !== 'voided'"
                        command="invoice-void">作废</el-dropdown-item>
    </template>

    <template #detail-head="{ detail }">
      <el-descriptions-item label="方向">
        {{ detail.invoice_direction_label || detail.invoice_direction }}
      </el-descriptions-item>
      <el-descriptions-item label="发票代码">{{ detail.invoice_code || '—' }}</el-descriptions-item>
      <el-descriptions-item label="开票日期">{{ fmtDate(detail.invoice_date) }}</el-descriptions-item>
      <el-descriptions-item label="票种">{{ detail.invoice_type || '—' }}</el-descriptions-item>
      <el-descriptions-item label="不含税 / 税额">
        {{ fmtMoney(detail.amount || 0) }} / {{ fmtMoney(detail.tax_amount || 0) }}
      </el-descriptions-item>
      <el-descriptions-item label="认证状态">
        {{ detail.auth_status_label || detail.auth_status }}
      </el-descriptions-item>
      <el-descriptions-item label="已核销">{{ fmtMoney(detail.allocated_amount || 0) }}</el-descriptions-item>
      <el-descriptions-item label="未核销">{{ fmtMoney(detail.unallocated_amount || 0) }}</el-descriptions-item>
    </template>
  </DocListPage>
</template>
