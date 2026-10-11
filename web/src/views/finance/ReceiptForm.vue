<script setup lang="ts">
/**
 * 收款单表单（V2.5）：付款单镜像。
 * 从销售订单列表「更多 → 发起收款单」进入时预填客户与**未收金额**。
 */
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AllocationTable from '@/components/doc/AllocationTable.vue'
import DocFormPage from '@/components/doc/DocFormPage.vue'
import { fetchDoc, fetchDocList, fetchFinanceMeta, fetchMasterOptions, type Dict } from '@/api'
import type { AllocationRow } from '@/types/doc'

const route = useRoute()
const formRef = ref<InstanceType<typeof DocFormPage> | null>(null)

const customers = ref<Dict[]>([])
const settleTypes = ref<string[]>([])
const orders = ref<Dict[]>([])
const allocations = ref<AllocationRow[]>([])
const extra = ref<Dict>({})
const partyId = ref<number | null>(null)
const settleType = ref<string>('')
const recvAccount = ref<string>('')
const totalAmount = ref<number>(0)

const TARGETS = [{ code: 'sales_order', label: '销售订单' }]

function sync() {
  extra.value = {
    customer_id: partyId.value || null,
    settle_type: settleType.value || null,
    recv_account: recvAccount.value || null,
    total_amount: Number(totalAmount.value || 0),
    allocations: allocations.value.map((r) => ({
      target_type: r.target_type,
      target_id: r.target_id,
      amount: Number(r.amount || 0),
      remark: r.remark || null,
    })),
  }
}
watch([partyId, settleType, recvAccount, totalAmount, allocations], sync, { deep: true })

async function loadOrders() {
  try {
    const data = await fetchDocList('/api/sales/orders', { status: 'approved', page_size: 200 })
    orders.value = data.items
  } catch {
    orders.value = []
  }
}

onMounted(async () => {
  try {
    settleTypes.value = (await fetchFinanceMeta()).settle_types || []
  } catch {
    settleTypes.value = []
  }
  try {
    customers.value = await fetchMasterOptions('customer')
  } catch {
    customers.value = []
  }
  await loadOrders()

  const sourceId = Number(route.query.source_id || 0)
  if (!route.params.id && route.query.source_type === 'sales_order' && sourceId) {
    try {
      const so = await fetchDoc('/api/sales/orders', sourceId)
      partyId.value = (so.customer_id as number) || null
      totalAmount.value = Math.max(0, Number(so.total_amount || 0) - Number(so.received_amount || 0))
      allocations.value = [{ target_type: 'sales_order', target_id: sourceId,
                             amount: totalAmount.value }]
      if (!orders.value.some((o) => o.id === sourceId)) orders.value = [so, ...orders.value]
      sync()
    } catch {
      // 预填失败不阻塞录入
    }
  }
})

watch(() => formRef.value?.detail, (detail: Dict | null | undefined) => {
  if (!detail || !detail.id || allocations.value.length) return
  partyId.value = (detail.customer_id as number) || null
  settleType.value = (detail.settle_type as string) || ''
  recvAccount.value = (detail.recv_account as string) || ''
  totalAmount.value = Number(detail.total_amount || 0)
  allocations.value = ((detail.allocations as AllocationRow[]) || []).map((r) => ({ ...r }))
  sync()
})
</script>

<template>
  <DocFormPage ref="formRef" v-model="extra" title="收款单" api="/api/finance/receipts"
               perm-prefix="finance.receipt" list-route="finance-receipts"
               kind-label="收款单" show-subject contract-source="sales"
               items-title="核销明细" :require-items="false" :submit-items="false">
    <template #header>
      <el-col :span="12">
        <el-form-item label="客户" required>
          <el-select v-model="partyId" filterable placeholder="选择客户" style="width: 100%">
            <el-option v-for="c in customers" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="收款金额" required>
          <el-input-number v-model="totalAmount" :min="0" :precision="2" :controls="false"
                           style="width: 100%" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="结算方式">
          <el-select v-model="settleType" clearable placeholder="银行转账 / 现金 / 承兑"
                     style="width: 100%">
            <el-option v-for="s in settleTypes" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="收款账户">
          <el-input v-model="recvAccount" placeholder="如 工行基本户 6222…" />
        </el-form-item>
      </el-col>
    </template>

    <template #items="{ readonly }">
      <AllocationTable v-model="allocations" :targets="TARGETS" :options="orders"
                       :readonly="readonly" :total-amount="totalAmount" />
    </template>
  </DocFormPage>
</template>
