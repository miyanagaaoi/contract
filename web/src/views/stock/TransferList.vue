<script setup lang="ts">
/**
 * 调拨单列表（V2.1 / N13）。
 *
 * 调拨是本版唯一"一单双向"的单据：审核即在同一事务内完成调出仓减少与调入仓增加。
 */
import DocListPage from '@/components/doc/DocListPage.vue'
import PostStatusTag from '@/components/doc/PostStatusTag.vue'
import { fmtDate } from '@/utils/format'
</script>

<template>
  <DocListPage title="调拨单" api="/api/stock/transfers"
               subtitle="审核即过账：同一事务内调出仓减少、调入仓增加（仓库间搬运，不产生金额）"
               perm-prefix="stock.transfer" kind-label="调拨单"
               form-route="stock-transfer-form" edit-route="stock-transfer-edit"
               list-route="stock-transfer-list"
               export-path="/api/stock/transfers/export.xlsx">
    <template #detail-head="{ detail }">
      <el-descriptions-item label="调出仓库">{{ detail.from_warehouse_name || '—' }}</el-descriptions-item>
      <el-descriptions-item label="调入仓库">{{ detail.to_warehouse_name || '—' }}</el-descriptions-item>
      <el-descriptions-item label="过账状态">
        <PostStatusTag :posted="detail.posted" />
      </el-descriptions-item>
      <el-descriptions-item label="审核时间">{{ fmtDate(detail.approved_at) }}</el-descriptions-item>
    </template>
  </DocListPage>
</template>
