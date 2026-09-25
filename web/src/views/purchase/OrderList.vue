<script setup lang="ts">
/**
 * 采购单列表（T-V2-24，AC-V2-18）：审核通过后可下推生成入库单。
 */
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import DocListPage from '@/components/doc/DocListPage.vue'
import PushDialog from '@/components/doc/PushDialog.vue'
import type { DocRecord } from '@/types/doc'

const router = useRouter()
const listRef = ref<InstanceType<typeof DocListPage> | null>(null)
const pushRef = ref<InstanceType<typeof PushDialog> | null>(null)

function onPush(row: DocRecord) {
  pushRef.value?.open(row)
}

/** 下推成功：跳到入库单编辑页（仓库/数量已预填） */
function onPushed(doc: DocRecord) {
  listRef.value?.load()
  router.push({ name: 'stock-in-edit', params: { id: String(doc.id) } })
}

function fmtMoney(v: unknown): string {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  return Number.isNaN(n) ? String(v) : n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtDate(v: unknown): string {
  return v ? String(v).slice(0, 10) : '—'
}
</script>

<template>
  <DocListPage ref="listRef" title="采购单" api="/api/purchase/orders"
               subtitle="向供应商下单 → 审核 → 下推入库单；入库过账后回写已入库数量"
               perm-prefix="purchase.order" kind-label="采购单"
               form-route="purchase-order-form" edit-route="purchase-order-edit" show-supplier show-warehouse
               pushable push-perm="purchase.order.push" :extra-cols="['received']"
               export-path="/api/purchase/orders/export.xlsx"
               @push="onPush">
    <template #detail-head="{ detail }">
      <el-descriptions-item label="预计到货">{{ fmtDate(detail.expected_arrival_date) }}</el-descriptions-item>
      <el-descriptions-item label="结算方式">{{ detail.settle_type || '—' }}</el-descriptions-item>
      <el-descriptions-item label="币种">{{ detail.currency || 'CNY' }}</el-descriptions-item>
      <el-descriptions-item label="收货仓库">
        {{ detail.receipt_warehouse_id ? `ID ${detail.receipt_warehouse_id}` : '—' }}
      </el-descriptions-item>
      <el-descriptions-item label="已生成入库单" :span="2">
        {{ detail.generated_in_no || '—' }}
      </el-descriptions-item>
      <el-descriptions-item label="单据金额" :span="2">{{ fmtMoney(detail.total_amount) }}</el-descriptions-item>
    </template>
  </DocListPage>

  <PushDialog ref="pushRef" api="/api/purchase/orders" dest-type="stock"
              dest-label="入库单" @done="onPushed" />
</template>
