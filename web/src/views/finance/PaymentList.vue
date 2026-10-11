<script setup lang="ts">
/**
 * 付款单列表（V2.5，AC-V2.5-02/06/16）。
 *
 * 动线：业务员在采购单列表「更多 → 发起付款单」→ 财务审核（**审核即记账**，回写采购单
 * `paid_amount`）→ 采购单的付款进度随即可见；反审核自动红冲（BR-V2.5-02）。
 */
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import DocListPage from '@/components/doc/DocListPage.vue'
import { recalcFinanceProgress, type Dict } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { fmtDate, fmtMoney } from '@/utils/format'

const auth = useAuthStore()
const listRef = ref<InstanceType<typeof DocListPage> | null>(null)
const overOnly = ref<boolean | ''>('')
const recalcLoading = ref(false)

/** 只有能记账的人（财务/管理员）才需要"重算"这个运维动作 */
const canRecalc = computed(() => auth.hasPerm('finance.payment.approve'))

/** 超额筛选走**库侧**参数（前端内存过滤会让分页与总数失真） */
const filterParams = computed<Dict>(() => ({ over: overOnly.value || undefined }))

async function onRecalc() {
  try {
    await ElMessageBox.confirm(
      '按核销明细重算采购单的已付金额（不改核销明细、不改单据状态）。'
      + '仅当怀疑回写值与明细不一致时使用；可安全重复执行。',
      '重算进度回写', { type: 'warning', confirmButtonText: '开始重算', cancelButtonText: '取消' })
  } catch {
    return
  }
  recalcLoading.value = true
  try {
    const result: Dict = await recalcFinanceProgress()
    ElMessage.success(`重算完成：检查 ${result.checked} 条，修正 ${result.fixed} 条`)
    listRef.value?.load()
  } catch {
    // 拦截器已提示
  } finally {
    recalcLoading.value = false
  }
}
</script>

<template>
  <DocListPage ref="listRef" title="付款单" api="/api/finance/payments"
               subtitle="业务员发起 → 财务审核（记账）→ 回写采购单已付金额；反审核自动红冲"
               perm-prefix="finance.payment" kind-label="付款单"
               form-route="finance-payment-form" edit-route="finance-payment-edit"
               detail-route="finance-payment-detail" show-supplier show-subject
               :extra-filter-params="filterParams"
               export-path="/api/finance/payments/export.xlsx">
    <template #extra-filters="{ reload }">
      <el-form-item label="核销">
        <el-select v-model="overOnly" clearable style="width: 128px" placeholder="全部"
                   @change="reload">
          <el-option label="只看超额" :value="true" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="canRecalc" label=" ">
        <el-button :loading="recalcLoading" @click="onRecalc">重算回写</el-button>
      </el-form-item>
    </template>

    <template #extra-columns>
      <el-table-column label="结算方式" width="110">
        <template #default="{ row }">{{ row.settle_type || '—' }}</template>
      </el-table-column>
      <el-table-column label="已核销" width="120" align="right">
        <template #default="{ row }">{{ fmtMoney(row.allocated_amount || 0) }}</template>
      </el-table-column>
      <el-table-column label="未核销" width="120" align="right">
        <template #default="{ row }">
          <span :class="Number(row.unallocated_amount) < 0 ? 'over' : ''">
            {{ fmtMoney(row.unallocated_amount || 0) }}
          </span>
        </template>
      </el-table-column>
    </template>

    <template #detail-head="{ detail }">
      <el-descriptions-item label="结算方式">{{ detail.settle_type || '—' }}</el-descriptions-item>
      <el-descriptions-item label="付款账户">{{ detail.pay_account || '—' }}</el-descriptions-item>
      <el-descriptions-item label="已核销">{{ fmtMoney(detail.allocated_amount || 0) }}</el-descriptions-item>
      <el-descriptions-item label="未核销">
        <span :class="Number(detail.unallocated_amount) < 0 ? 'over' : ''">
          {{ fmtMoney(detail.unallocated_amount || 0) }}
        </span>
      </el-descriptions-item>
      <el-descriptions-item label="来源单据">{{ detail.source_doc_no || '—' }}</el-descriptions-item>
      <el-descriptions-item label="审核时间">{{ fmtDate(detail.approved_at) }}</el-descriptions-item>
    </template>
  </DocListPage>
</template>

<style scoped>
.over { color: var(--ctms-danger-text); }
</style>
