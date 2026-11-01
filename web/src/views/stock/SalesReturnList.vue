<script setup lang="ts">
/**
 * 销售退货单列表（CR-034）：入库方向，审核后回冲销售订单已发数量。
 */
import DocListPage from '@/components/doc/DocListPage.vue'
import PostStatusTag from '@/components/doc/PostStatusTag.vue'
import { fmtDate } from '@/utils/format'

const printSignerLabels = ['库管员', '采购人', '财务', '部门负责人', '部门负责人']
</script>

<template>
  <DocListPage title="销售退货单" api="/api/stock/sales-returns"
               subtitle="客户退货入库：审核即入库过账，并从销售订单「已发数量」中扣回"
               perm-prefix="stock.in" kind-label="销售退货单"
               form-route="stock-sales-return-form"
               edit-route="stock-sales-return-edit"
               list-route="stock-sales-returns"
               show-warehouse show-customer show-subject
               export-path="/api/stock/sales-returns/export.xlsx"
               :print-signer-labels="printSignerLabels">
    <template #detail-head="{ detail }">
      <el-descriptions-item label="过账状态">
        <PostStatusTag :posted="detail.posted" />
      </el-descriptions-item>
      <el-descriptions-item label="来源销售订单" :span="2">
        {{ detail.source_doc_no || '—' }}
      </el-descriptions-item>
      <el-descriptions-item label="审核时间" :span="2">
        {{ fmtDate(detail.approved_at) }}
      </el-descriptions-item>
    </template>
  </DocListPage>
</template>
