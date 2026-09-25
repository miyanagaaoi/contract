<script setup lang="ts">
/**
 * 销售订单列表（T-V2-30，与采购单同构）：审核通过后可下推生成出库单。
 *
 * 特有：默认按 `shipped_qty` 计算剩余可下推量（已出库），详情展示交货 / 收货与已生成出库单号。
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

/** 下推成功：跳到出库单编辑页（仓库 / 客户已预填） */
function onPushed(doc: DocRecord) {
  listRef.value?.load()
  router.push({ name: 'stock-out-edit', params: { id: String(doc.id) } })
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
  <DocListPage ref="listRef" title="销售订单" api="/api/sales/orders"
               subtitle="确认客户与交期 → 审核 → 下推出库单；出库过账后回写已出库数量"
               perm-prefix="sales.order" kind-label="销售订单"
               form-route="sales-order-form" edit-route="sales-order-edit"
               show-customer show-warehouse
               contract-source="sales" export-path="/api/sales/orders/export.xlsx"
               pushable push-perm="sales.order.push" :extra-cols="['shipped']"
               @push="onPush">
    <template #detail-head="{ detail }">
      <el-descriptions-item label="交货日期">{{ fmtDate(detail.delivery_date) }}</el-descriptions-item>
      <el-descriptions-item label="币种">{{ detail.currency || 'CNY' }}</el-descriptions-item>
      <el-descriptions-item label="联系人">{{ detail.contact_name || '—' }}</el-descriptions-item>
      <el-descriptions-item label="联系电话">{{ detail.contact_phone || '—' }}</el-descriptions-item>
      <el-descriptions-item label="发运仓库">
        {{ detail.ship_warehouse_id ? `ID ${detail.ship_warehouse_id}` : '—' }}
      </el-descriptions-item>
      <el-descriptions-item label="已生成出库单">{{ detail.generated_out_no || '—' }}</el-descriptions-item>
      <el-descriptions-item label="收货地址" :span="2">{{ detail.delivery_address || '—' }}</el-descriptions-item>
      <el-descriptions-item label="销售部门" :span="2">
        {{ detail.sales_dept_id ? `ID ${detail.sales_dept_id}` : '—' }}
      </el-descriptions-item>
      <el-descriptions-item label="单据金额" :span="2">{{ fmtMoney(detail.total_amount) }}</el-descriptions-item>
    </template>
  </DocListPage>

  <PushDialog ref="pushRef" api="/api/sales/orders" dest-type="stock"
              dest-label="出库单" used-field="shipped_qty"
              stock-type-field="out_type" :stock-type-options="['销售出库', '领用出库', '其他出库']"
              warehouse-label="出库仓库" @done="onPushed" />
</template>
