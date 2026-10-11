<script setup lang="ts">
/**
 * 付款单表单（V2.5，AC-V2.5-01/14）。
 *
 * 从采购单列表「更多 → 发起付款单」进入时带 `?source_type=purchase_order&source_id=<id>`：
 * 预填供应商、金额（= **未付金额**）与一行核销明细，并把该采购单塞进下拉候选
 * （它可能不在"最近 200 张已审核采购单"里）。预填只是默认值，财务可改成部分付款。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AllocationTable from '@/components/doc/AllocationTable.vue'
import DocFormPage from '@/components/doc/DocFormPage.vue'
import { fetchDoc, fetchDocList, fetchFinanceMeta, fetchMasterOptions, type Dict } from '@/api'
import type { AllocationRow } from '@/types/doc'

const route = useRoute()
const formRef = ref<InstanceType<typeof DocFormPage> | null>(null)

const suppliers = ref<Dict[]>([])
const settleTypes = ref<string[]>([])
const orders = ref<Dict[]>([{ id: 0, doc_no: '', total_amount: 0 }].slice(1))
const allocations = ref<AllocationRow[]>([])
const extra = ref<Dict>({})
const partyId = ref<number | null>(null)
const settleType = ref<string>('')
const payAccount = ref<string>('')
const totalAmount = ref<number>(0)

const TARGETS = [{ code: 'purchase_order', label: '采购单' }]

/** 把UI状态同步进 DocFormPage 的扩展字段（保存时原样提交给后端） */
function sync() {
  extra.value = {
    supplier_id: partyId.value || null,
    settle_type: settleType.value || null,
    pay_account: payAccount.value || null,
    total_amount: Number(totalAmount.value || 0),
    allocations: allocations.value.map((r) => ({
      target_type: r.target_type,
      target_id: r.target_id,
      amount: Number(r.amount || 0),
      remark: r.remark || null,
    })),
  }
}
watch([partyId, settleType, payAccount, totalAmount, allocations], sync, { deep: true })

/** 已审核采购单候选（M1 一次只核销一张，故取最近 200 张即可） */
async function loadOrders() {
  try {
    const data = await fetchDocList('/api/purchase/orders', { status: 'approved', page_size: 200 })
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
    suppliers.value = await fetchMasterOptions('supplier')
  } catch {
    suppliers.value = []
  }
  await loadOrders()

  const sourceId = Number(route.query.source_id || 0)
  if (!route.params.id && route.query.source_type === 'purchase_order' && sourceId) {
    try {
      const po = await fetchDoc('/api/purchase/orders', sourceId)
      partyId.value = (po.supplier_id as number) || null
      settleType.value = (po.settle_type as string) || ''
      // 预填"未付金额"（含税）：已付由付款单核销回写，故这里用只读快照字段
      totalAmount.value = Math.max(0, Number(po.total_amount || 0) - Number(po.paid_amount || 0))
      allocations.value = [{ target_type: 'purchase_order', target_id: sourceId,
                             amount: totalAmount.value }]
      if (!orders.value.some((o) => o.id === sourceId)) orders.value = [po, ...orders.value]
      sync()
    } catch {
      // 预填失败不阻塞录入（用户可手选）
    }
  }
})

/** 编辑已保存单据：把落库值填回表单（详情由 DocFormPage 异步加载） */
watch(() => formRef.value?.detail, (detail: Dict | null | undefined) => {
  if (!detail || !detail.id || allocations.value.length) return
  partyId.value = (detail.supplier_id as number) || null
  settleType.value = (detail.settle_type as string) || ''
  payAccount.value = (detail.pay_account as string) || ''
  totalAmount.value = Number(detail.total_amount || 0)
  allocations.value = ((detail.allocations as AllocationRow[]) || []).map((r) => ({ ...r }))
  sync()
})
</script>

<template>
  <DocFormPage ref="formRef" v-model="extra" title="付款单" api="/api/finance/payments"
               perm-prefix="finance.payment" list-route="finance-payments"
               kind-label="付款单" show-subject contract-source="purchase"
               items-title="核销明细" :require-items="false" :submit-items="false">
    <template #header>
      <el-col :span="12">
        <el-form-item label="供应商" required>
          <el-select v-model="partyId" filterable placeholder="选择供应商" style="width: 100%">
            <el-option v-for="s in suppliers" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="付款金额" required>
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
        <el-form-item label="付款账户">
          <el-input v-model="payAccount" placeholder="如 工行基本户 6222…" />
        </el-form-item>
      </el-col>
    </template>

    <template #items="{ readonly }">
      <AllocationTable v-model="allocations" :targets="TARGETS" :options="orders"
                       :readonly="readonly" :total-amount="totalAmount" />
    </template>
  </DocFormPage>
</template>
