<script setup lang="ts">
/**
 * 采购单列表（T-V2-24，AC-V2-18）：审核通过后可下推生成入库单。
 *
 * V2.5 新增：收货/付款/收票三列进度，以及「更多 → 发起付款单 / 登记进项发票」
 * 快速入口（预填供应商、签约公司、未付/未收票金额与来源单号）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import DocListPage from '@/components/doc/DocListPage.vue'
import PushDialog from '@/components/doc/PushDialog.vue'
import { fetchMasterOptions, type Dict } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { DocRecord } from '@/types/doc'
import { fmtDate, fmtMoney } from '@/utils/format'

const router = useRouter()
const auth = useAuthStore()
const listRef = ref<InstanceType<typeof DocListPage> | null>(null)
const pushRef = ref<InstanceType<typeof PushDialog> | null>(null)

/** V2.5：财务发起入口按权限显隐（后端仍强制校验，前端只决定"看不看得见"） */
const canInitPayment = computed(() => auth.hasPerm('finance.payment.create'))
const canInitInvoice = computed(() => auth.hasPerm('finance.invoice.create'))

function onPush(row: DocRecord) {
  pushRef.value?.open(row)
}

/** 下推成功：跳到入库单编辑页（仓库/数量已预填） */
function onPushed(doc: DocRecord) {
  listRef.value?.load()
  router.push({ name: 'stock-in-edit', params: { id: String(doc.id) } })
}

/** V2.5：「更多」里的财务动作（DocListPage 不认识的命令统一走 `more` 事件） */
function onMore({ command, row }: { command: string; row: DocRecord }) {
  if (command === 'pay') {
    router.push({ name: 'finance-payment-form',
                  query: { source_type: 'purchase_order', source_id: String(row.id) } })
  } else if (command === 'invoice-in') {
    router.push({ name: 'finance-invoice-form',
                  query: { source_type: 'purchase_order', source_id: String(row.id),
                           direction: 'in' } })
  }
}

/** 只有已审核/已完成的单据才能发起下游财务动作（与"下推"的显隐口径一致） */
function initiable(row: DocRecord): boolean {
  return row.status === 'approved' || row.status === 'completed'
}

// fmtMoney / fmtDate 统一走 @/utils/format（T1-3）

/** 收货仓库显示名（详情抽屉里避免只显示 ID） */
const warehouses = ref<Dict[]>([])

function warehouseName(id: unknown): string {
  if (!id) return '—'
  const hit = warehouses.value.find((w) => w.id === Number(id))
  // V2.3：仓库默认显示 `主体码-仓库名`（ZC-主仓）
  return hit ? ((hit.display_name as string) || (hit.name as string)) : `已删除/无权限的仓库（#${id}）`
}

onMounted(async () => {
  try {
    warehouses.value = await fetchMasterOptions('warehouse')
  } catch {
    warehouses.value = []
  }
})
</script>

<template>
  <DocListPage ref="listRef" title="采购单" api="/api/purchase/orders"
               subtitle="向供应商下单 → 审核 → 下推入库单；入库过账后回写已入库数量，付款/收票由财务单据回写"
               perm-prefix="purchase.order" kind-label="采购单"
               form-route="purchase-order-form" edit-route="purchase-order-edit" show-supplier show-warehouse
               show-subject
               pushable push-perm="purchase.order.push" :extra-cols="['received']"
               push-remain-field="remain_qty_sum"
               :progress-cols="['received_qty', 'paid_amount', 'invoiced_amount']"
               :progress-labels="{ invoiced_amount: '收票进度' }"
               export-path="/api/purchase/orders/export.xlsx"
               @push="onPush" @more="onMore">
    <template #more-actions="{ row }">
      <el-dropdown-item v-if="canInitPayment && initiable(row)" divided command="pay">
        发起付款单
      </el-dropdown-item>
      <el-dropdown-item v-if="canInitInvoice && initiable(row)" command="invoice-in">
        登记进项发票
      </el-dropdown-item>
    </template>

    <template #detail-head="{ detail }">
      <el-descriptions-item label="预计到货">{{ fmtDate(detail.expected_arrival_date) }}</el-descriptions-item>
      <el-descriptions-item label="结算方式">{{ detail.settle_type || '—' }}</el-descriptions-item>
      <el-descriptions-item label="币种">{{ detail.currency || 'CNY' }}</el-descriptions-item>
      <el-descriptions-item label="收货仓库">
        {{ warehouseName(detail.receipt_warehouse_id) }}
      </el-descriptions-item>
      <el-descriptions-item label="已生成入库单" :span="2">
        {{ detail.generated_in_no || '—' }}
      </el-descriptions-item>
      <el-descriptions-item label="单据金额" :span="2">{{ fmtMoney(detail.total_amount) }}</el-descriptions-item>
      <!-- V2.5：财务进度（含税口径；收货进度在行项里也有） -->
      <el-descriptions-item label="已付 / 已收票" :span="2">
        {{ fmtMoney(detail.paid_amount || 0) }} / {{ fmtMoney(detail.invoiced_amount || 0) }}
      </el-descriptions-item>
      <!-- V2.5：已生成的付款单/进项发票（来源单据快照，AC-V2.5-14） -->
      <el-descriptions-item label="已生成付款单/发票" :span="2">
        <template v-if="(detail.finance_docs || []).length">
          <span v-for="fd in detail.finance_docs" :key="`${fd.kind}-${fd.doc_no}`" class="fin-doc">
            {{ fd.kind_label }} {{ fd.doc_no }}（{{ fmtMoney(fd.amount) }}）
          </span>
        </template>
        <span v-else>—</span>
      </el-descriptions-item>
    </template>
  </DocListPage>

  <PushDialog ref="pushRef" api="/api/purchase/orders" dest-type="stock"
              dest-label="入库单" @done="onPushed" />
</template>

