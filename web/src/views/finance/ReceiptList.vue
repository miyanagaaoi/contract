<script setup lang="ts">
/**
 * 收款单列表（V2.5）：付款单镜像 —— 收客户货款并按销售订单核销，回写 `received_amount`。
 */
import { computed, ref } from 'vue'

import DocListPage from '@/components/doc/DocListPage.vue'
import type { Dict } from '@/api'
import { fmtDate, fmtMoney } from '@/utils/format'

const listRef = ref<InstanceType<typeof DocListPage> | null>(null)
const overOnly = ref<boolean | ''>('')

const filterParams = computed<Dict>(() => ({ over: overOnly.value || undefined }))
</script>

<template>
  <DocListPage ref="listRef" title="收款单" api="/api/finance/receipts"
               subtitle="业务员发起 → 财务审核（记账）→ 回写销售订单已收金额；反审核自动红冲"
               perm-prefix="finance.receipt" kind-label="收款单"
               form-route="finance-receipt-form" edit-route="finance-receipt-edit"
               detail-route="finance-receipt-detail" show-customer show-subject
               :extra-filter-params="filterParams"
               export-path="/api/finance/receipts/export.xlsx">
    <template #extra-filters="{ reload }">
      <el-form-item label="核销">
        <el-select v-model="overOnly" clearable style="width: 128px" placeholder="全部"
                   @change="reload">
          <el-option label="只看超额" :value="true" />
        </el-select>
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
      <el-descriptions-item label="收款账户">{{ detail.recv_account || '—' }}</el-descriptions-item>
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
