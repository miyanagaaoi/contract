<script setup lang="ts">
/**
 * 出库单列表（T-V2-25）：与入库单同构，**审核即过账**（负库存会被拦截）。
 * 打印走「选人 → 预填签字」流程：签字位与后端打印模板默认值同口径。
 *
 * V2.6.1 / CR-022：新增「更多 → 退库」——按已审核出库单勾选行与数量，
 * 生成一张草稿「退库入库单」（类型=退库入库，来源指向本出库单），审核后过账。
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import DocListPage from '@/components/doc/DocListPage.vue'
import PostStatusTag from '@/components/doc/PostStatusTag.vue'
import StockReturnDialog from '@/components/stock/StockReturnDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { fmtDate } from '@/utils/format'
import type { Dict } from '@/api'

const router = useRouter()
const auth = useAuthStore()

/** 出库单默认签字栏（与后端 print_template_service.STOCK_SIGN_LABELS 同口径） */
const printSignerLabels = ['库管员', '采购人', '财务', '部门负责人', '部门负责人']

/** CR-022：退库权限与弹窗状态 */
const canReturn = computed(() => auth.hasPerm('stock.in.create'))
const returnVisible = ref(false)
const returnDoc = ref<Dict | null>(null)

function onMore({ command, row }: { command: string; row: Dict }) {
  if (command === 'return') {
    returnDoc.value = row
    returnVisible.value = true
  }
}

/** 退库成功后跳转到新建的退库入库单（继续编辑/审核） */
function onReturned(newDoc: Dict) {
  if (newDoc?.id) {
    router.push({ name: 'stock-in-edit', params: { id: String(newDoc.id) } })
  }
}
</script>

<template>
  <DocListPage title="出库单" api="/api/stock/out-orders"
               subtitle="审核即过账（写入库存流水，负库存拦截）；出库类型：销售出库 / 领用出库 / 其他出库"
               perm-prefix="stock.out" kind-label="出库单"
               form-route="stock-out-form" edit-route="stock-out-edit" list-route="stock-out-orders"
               show-warehouse show-customer show-subject
               export-path="/api/stock/out-orders/export.xlsx"
               :extra-cols="['shipped']"
               :print-signer-labels="printSignerLabels"
               @more="onMore">
    <!-- V2.6.1 / CR-022：已审核出库单可发起退库 -->
    <template #more-actions="{ row }">
      <el-dropdown-item v-if="canReturn && row.status === 'approved'" divided command="return">
        退库
      </el-dropdown-item>
    </template>

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

  <!-- V2.6.1 / CR-022：退库弹窗（勾选行 + 数量 → 生成退库入库单） -->
  <StockReturnDialog v-model="returnVisible" :doc="returnDoc" @done="onReturned" />
</template>
