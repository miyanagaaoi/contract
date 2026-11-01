<script setup lang="ts">
/**
 * 采购退货单列表（CR-034）：出库方向，审核后回冲采购单已收数量。
 */
import DocListPage from '@/components/doc/DocListPage.vue'
import PostStatusTag from '@/components/doc/PostStatusTag.vue'
import { fmtDate } from '@/utils/format'

const printSignerLabels = ['库管员', '采购人', '财务', '部门负责人', '部门负责人']
</script>

<template>
  <DocListPage title="采购退货单" api="/api/stock/purchase-returns"
               subtitle="退货给供应商：审核即出库过账，并从采购单「已收数量」中扣回"
               perm-prefix="stock.out" kind-label="采购退货单"
               form-route="stock-purchase-return-form"
               edit-route="stock-purchase-return-edit"
               list-route="stock-purchase-returns"
               show-warehouse show-supplier show-subject
               export-path="/api/stock/purchase-returns/export.xlsx"
               :print-signer-labels="printSignerLabels">
    <template #detail-head="{ detail }">
      <el-descriptions-item label="过账状态">
        <PostStatusTag :posted="detail.posted" />
      </el-descriptions-item>
      <el-descriptions-item label="来源采购单" :span="2">
        {{ detail.source_doc_no || '—' }}
      </el-descriptions-item>
      <el-descriptions-item label="审核时间" :span="2">
        {{ fmtDate(detail.approved_at) }}
      </el-descriptions-item>
    </template>
  </DocListPage>
</template>
