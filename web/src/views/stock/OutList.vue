<script setup lang="ts">
/**
 * 出库单列表（T-V2-25）：与入库单同构，**审核即过账**（负库存会被拦截）。
 */
import DocListPage from '@/components/doc/DocListPage.vue'
import PostStatusTag from '@/components/doc/PostStatusTag.vue'
import { fmtDate } from '@/utils/format'
</script>

<template>
  <DocListPage title="出库单" api="/api/stock/out-orders"
               subtitle="审核即过账（写入库存流水，负库存拦截）；出库类型：销售出库 / 领用出库 / 其他出库"
               perm-prefix="stock.out" kind-label="出库单"
               form-route="stock-out-form" edit-route="stock-out-edit" list-route="stock-out-orders"
               show-warehouse show-customer
               export-path="/api/stock/out-orders/export.xlsx"
               :extra-cols="['shipped']">
    <template #detail-head="{ detail }">
      <el-descriptions-item label="出库类型">{{ detail.out_type || '—' }}</el-descriptions-item>
      <el-descriptions-item label="过账状态">
        <PostStatusTag :posted="detail.posted" />
      </el-descriptions-item>
      <el-descriptions-item label="来源销售订单" :span="2">{{ detail.source_doc_no || '—' }}</el-descriptions-item>
      <el-descriptions-item label="审核时间" :span="2">
        {{ fmtDate(detail.approved_at) }}
      </el-descriptions-item>
    </template>
  </DocListPage>
</template>
