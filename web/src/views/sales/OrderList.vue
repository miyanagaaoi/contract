<script setup lang="ts">
/**
 * 销售订单列表（T-V2-30，与采购单同构）：审核通过后可下推生成出库单。
 *
 * 特有：默认按 `shipped_qty` 计算剩余可下推量（已出库），详情展示交货 / 收货与已生成出库单号。
 *
 * V2.5 新增：发货/收款/开票三列进度，以及「更多 → 发起收款单 / 登记销项发票」快速入口。
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

/** V2.5：财务发起入口按权限显隐（后端仍强制校验） */
const canInitReceipt = computed(() => auth.hasPerm('finance.receipt.create'))
const canInitInvoice = computed(() => auth.hasPerm('finance.invoice.create'))

/** V2.5：「更多」里的财务动作（DocListPage 不认识的命令统一走 `more` 事件） */
function onMore({ command, row }: { command: string; row: DocRecord }) {
  if (command === 'receipt') {
    router.push({ name: 'finance-receipt-form',
                  query: { source_type: 'sales_order', source_id: String(row.id) } })
  } else if (command === 'invoice-out') {
    router.push({ name: 'finance-invoice-form',
                  query: { source_type: 'sales_order', source_id: String(row.id),
                           direction: 'out' } })
  }
}

/** 只有已审核/已完成的单据才能发起下游财务动作（与"下推"的显隐口径一致） */
function initiable(row: DocRecord): boolean {
  return row.status === 'approved' || row.status === 'completed'
}

function onPush(row: DocRecord) {
  pushRef.value?.open(row)
}

/** 下推成功：跳到出库单编辑页（仓库 / 客户已预填） */
function onPushed(doc: DocRecord) {
  listRef.value?.load()
  router.push({ name: 'stock-out-edit', params: { id: String(doc.id) } })
}

// fmtMoney / fmtDate 统一走 @/utils/format（T1-3）

/** 部门 / 仓库显示名（详情抽屉里避免只显示 ID） */
const orgs = ref<Dict[]>([])
const warehouses = ref<Dict[]>([])

function deptName(id: unknown): string {
  if (!id) return '—'
  const hit = orgs.value.find((o) => o.id === Number(id))
  return hit ? hit.name : `已删除/无权限的部门（#${id}）`
}

function warehouseName(id: unknown): string {
  if (!id) return '—'
  const hit = warehouses.value.find((w) => w.id === Number(id))
  // V2.3：仓库默认显示 `主体码-仓库名`（ZC-主仓）
  return hit ? ((hit.display_name as string) || (hit.name as string)) : `已删除/无权限的仓库（#${id}）`
}

onMounted(async () => {
  try {
    const [o, w] = await Promise.all([fetchMasterOptions('org'), fetchMasterOptions('warehouse')])
    orgs.value = o
    warehouses.value = w
  } catch {
    orgs.value = []
    warehouses.value = []
  }
})
</script>

<template>
  <DocListPage ref="listRef" title="销售订单" api="/api/sales/orders"
               subtitle="确认客户与交期 → 审核 → 下推出库单；出库过账后回写已出库数量，收款/开票由财务单据回写"
               perm-prefix="sales.order" kind-label="销售订单"
               form-route="sales-order-form" edit-route="sales-order-edit"
               show-customer show-warehouse show-subject
               contract-source="sales" export-path="/api/sales/orders/export.xlsx"
               pushable push-perm="sales.order.push" :extra-cols="['shipped']"
               push-remain-field="remain_qty_sum"
               :progress-cols="['shipped_qty', 'received_amount', 'invoiced_amount']"
               :progress-labels="{ invoiced_amount: '开票进度' }"
               @push="onPush" @more="onMore">
    <template #more-actions="{ row }">
      <el-dropdown-item v-if="canInitReceipt && initiable(row)" divided command="receipt">
        发起收款单
      </el-dropdown-item>
      <el-dropdown-item v-if="canInitInvoice && initiable(row)" command="invoice-out">
        登记销项发票
      </el-dropdown-item>
    </template>
    <template #detail-head="{ detail }">
      <el-descriptions-item label="交货日期">{{ fmtDate(detail.delivery_date) }}</el-descriptions-item>
      <el-descriptions-item label="币种">{{ detail.currency || 'CNY' }}</el-descriptions-item>
      <el-descriptions-item label="联系人">{{ detail.contact_name || '—' }}</el-descriptions-item>
      <el-descriptions-item label="联系电话">{{ detail.contact_phone || '—' }}</el-descriptions-item>
      <el-descriptions-item label="发运仓库">
        {{ warehouseName(detail.ship_warehouse_id) }}
      </el-descriptions-item>
      <el-descriptions-item label="已生成出库单">{{ detail.generated_out_no || '—' }}</el-descriptions-item>
      <el-descriptions-item label="收货地址" :span="2">{{ detail.delivery_address || '—' }}</el-descriptions-item>
      <el-descriptions-item label="销售部门" :span="2">
        {{ deptName(detail.sales_dept_id) }}
      </el-descriptions-item>
      <el-descriptions-item label="单据金额" :span="2">{{ fmtMoney(detail.total_amount) }}</el-descriptions-item>
      <!-- V2.5：已生成的收款单/销项发票（来源单据快照，AC-V2.5-14） -->
      <el-descriptions-item label="已生成收款单/发票" :span="2">
        <template v-if="(detail.finance_docs || []).length">
          <span v-for="fd in detail.finance_docs" :key="`${fd.kind}-${fd.doc_no}`" class="fin-doc">
            {{ fd.kind_label }} {{ fd.doc_no }}（{{ fmtMoney(fd.amount) }}）
          </span>
        </template>
        <span v-else>—</span>
      </el-descriptions-item>
    </template>
  </DocListPage>

  <PushDialog ref="pushRef" api="/api/sales/orders" dest-type="stock"
              dest-label="出库单" used-field="shipped_qty"
              stock-type-field="out_type" :stock-type-options="['销售出库', '领用出库', '其他出库']"
              warehouse-label="出库仓库" @done="onPushed" />
</template>
