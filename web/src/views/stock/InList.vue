<script setup lang="ts">
/**
 * 入库单列表（T-V2-25）：**审核即过账**，界面对 `posted` 给出提示。
 * 打印走「选人 → 预填签字」流程：签字位与后端打印模板默认值同口径。
 */
import DocListPage from '@/components/doc/DocListPage.vue'
import PostStatusTag from '@/components/doc/PostStatusTag.vue'
import { fmtDate } from '@/utils/format'

/** 入库单默认签字栏（与后端 print_template_service.STOCK_SIGN_LABELS 同口径） */
const printSignerLabels = ['库管员', '采购人', '财务', '部门负责人', '部门负责人']
</script>

<template>
  <DocListPage title="入库单" api="/api/stock/in-orders"
               subtitle="审核即过账（写入库存流水）；入库类型：采购入库 / 退货入库 / 退库入库 / 其他入库"
               perm-prefix="stock.in" kind-label="入库单"
               form-route="stock-in-form" edit-route="stock-in-edit" list-route="stock-in-orders"
               show-warehouse show-supplier show-subject
               export-path="/api/stock/in-orders/export.xlsx"
               :extra-cols="['received']"
                :print-signer-labels="printSignerLabels">
    <template #detail-head="{ detail }">
      <el-descriptions-item label="入库类型">{{ detail.in_type || '—' }}</el-descriptions-item>
      <el-descriptions-item label="过账状态">
        <PostStatusTag :posted="detail.posted" />
      </el-descriptions-item>
      <el-descriptions-item label="来源采购单" :span="2">{{ detail.source_doc_no || '—' }}</el-descriptions-item>
      <el-descriptions-item label="审核时间" :span="2">
        {{ fmtDate(detail.approved_at) }}
      </el-descriptions-item>
    </template>
  </DocListPage>
</template>
