<script setup lang="ts">
/**
 * 发票表单（V2.5）：票面信息 + 核销明细。
 *
 * 方向决定一切：进项票的往来单位是**供应商**、核销目标是**采购单**；
 * 销项票是客户与销售订单。因此切换方向时会清空往来单位与核销明细，避免提交出
 * "进项票核销销售订单"这类被后端拒绝的组合（AC-V2.5-09）。
 *
 * 从采购单/销售订单「更多 → 登记发票」进入时带 `source_type/source_id/direction`，
 * 预填往来单位、价税合计（= 未收票/未开票金额）与一行核销明细。
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
const customers = ref<Dict[]>([])
const invoiceTypes = ref<string[]>([])
const orders = ref<Dict[]>([])
const allocations = ref<AllocationRow[]>([])
const extra = ref<Dict>({})

const direction = ref<'in' | 'out'>('in')
const invoiceNo = ref('')
const invoiceCode = ref('')
const invoiceType = ref('')
const invoiceDate = ref<string>('')
const taxRate = ref<number | null>(null)
const amount = ref<number>(0)
const taxAmount = ref<number>(0)
const totalAmount = ref<number>(0)
const authStatus = ref<'pending' | 'verified'>('pending')
const partyId = ref<number | null>(null)

const isEdit = computed(() => !!route.params.id)
const isIn = computed(() => direction.value === 'in')
const targets = computed(() => (isIn.value
  ? [{ code: 'purchase_order', label: '采购单' }]
  : [{ code: 'sales_order', label: '销售订单' }]))
const parties = computed(() => (isIn.value ? suppliers.value : customers.value))
const partyLabel = computed(() => (isIn.value ? '供应商' : '客户'))

/** 价税合计：填了不含税与税额就自动算（用户仍可手改，例如票面有差异） */
watch([amount, taxAmount], () => {
  const sum = Number(amount.value || 0) + Number(taxAmount.value || 0)
  if (sum > 0) totalAmount.value = Number(sum.toFixed(2))
})

function sync() {
  extra.value = {
    invoice_direction: direction.value,
    invoice_no: invoiceNo.value || null,
    invoice_code: invoiceCode.value || null,
    invoice_type: invoiceType.value || null,
    invoice_date: invoiceDate.value || null,
    tax_rate: taxRate.value,
    amount: Number(amount.value || 0),
    tax_amount: Number(taxAmount.value || 0),
    total_amount: Number(totalAmount.value || 0),
    auth_status: authStatus.value,
    ...(isIn.value ? { supplier_id: partyId.value || null } : { customer_id: partyId.value || null }),
    allocations: allocations.value.map((r) => ({
      target_type: r.target_type,
      target_id: r.target_id,
      amount: Number(r.amount || 0),
      tax_amount: Number(r.tax_amount || 0),
      remark: r.remark || null,
    })),
  }
}
watch([direction, invoiceNo, invoiceCode, invoiceType, invoiceDate, taxRate, amount, taxAmount,
       totalAmount, authStatus, partyId, allocations], sync, { deep: true })

/** 方向切换：往来单位与核销目标必须跟着换（否则提交会被"方向不符"拒绝） */
watch(direction, () => {
  partyId.value = null
  allocations.value = []
  loadOrders()
})

async function loadOrders() {
  try {
    const api = isIn.value ? '/api/purchase/orders' : '/api/sales/orders'
    const data = await fetchDocList(api, { status: 'approved', page_size: 200 })
    orders.value = data.items
  } catch {
    orders.value = []
  }
}

onMounted(async () => {
  try {
    const meta: Dict = await fetchFinanceMeta()
    invoiceTypes.value = meta.invoice_types || []
  } catch {
    invoiceTypes.value = []
  }
  try {
    suppliers.value = await fetchMasterOptions('supplier')
    customers.value = await fetchMasterOptions('customer')
  } catch {
    suppliers.value = []
    customers.value = []
  }

  const q = route.query
  if (q.direction === 'out') direction.value = 'out'
  await loadOrders()

  const sourceId = Number(q.source_id || 0)
  if (!isEdit.value && sourceId && q.source_type) {
    try {
      const api = q.source_type === 'sales_order' ? '/api/sales/orders' : '/api/purchase/orders'
      const doc = await fetchDoc(api, sourceId)
      const isPurchase = q.source_type === 'purchase_order'
      direction.value = isPurchase ? 'in' : 'out'
      partyId.value = (isPurchase ? doc.supplier_id : doc.customer_id) as number || null
      // 预填"未收票/未开票金额"（含税）
      totalAmount.value = Math.max(0, Number(doc.total_amount || 0)
        - Number(doc.invoiced_amount || 0))
      amount.value = Number((totalAmount.value / 1.13).toFixed(2))
      taxAmount.value = Number((totalAmount.value - amount.value).toFixed(2))
      taxRate.value = 13
      allocations.value = [{ target_type: isPurchase ? 'purchase_order' : 'sales_order',
                             target_id: sourceId, amount: totalAmount.value,
                             tax_amount: taxAmount.value }]
      await loadOrders()
      if (!orders.value.some((o) => o.id === sourceId)) orders.value = [doc, ...orders.value]
      sync()
    } catch {
      // 预填失败不阻塞录入
    }
  }
})

/** 编辑已保存发票：填回落库值（详情由 DocFormPage 异步加载） */
watch(() => formRef.value?.detail, (detail: Dict | null | undefined) => {
  if (!detail || !detail.id || invoiceNo.value) return
  direction.value = (detail.invoice_direction as 'in' | 'out') || 'in'
  invoiceNo.value = (detail.invoice_no as string) || ''
  invoiceCode.value = (detail.invoice_code as string) || ''
  invoiceType.value = (detail.invoice_type as string) || ''
  invoiceDate.value = (detail.invoice_date as string) || ''
  taxRate.value = detail.tax_rate === null || detail.tax_rate === undefined
    ? null : Number(detail.tax_rate)
  amount.value = Number(detail.amount || 0)
  taxAmount.value = Number(detail.tax_amount || 0)
  totalAmount.value = Number(detail.total_amount || 0)
  authStatus.value = (detail.auth_status as 'pending' | 'verified') || 'pending'
  partyId.value = (detail.party_id as number) || null
  allocations.value = ((detail.allocations as AllocationRow[]) || []).map((r) => ({ ...r }))
  loadOrders()
  sync()
})
</script>

<template>
  <DocFormPage ref="formRef" v-model="extra" title="发票" api="/api/finance/invoices"
               perm-prefix="finance.invoice" list-route="finance-invoices"
               kind-label="发票" show-subject contract-source="purchase"
               items-title="核销明细" :require-items="false" :submit-items="false">
    <template #header>
      <el-col :span="12">
        <el-form-item label="发票方向" required>
          <el-select v-model="direction" :disabled="isEdit" style="width: 100%">
            <el-option label="进项发票（供应商开给我方）" value="in" />
            <el-option label="销项发票（我方开给客户）" value="out" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item :label="partyLabel" required>
          <el-select v-model="partyId" filterable :placeholder="`选择${partyLabel}`"
                     style="width: 100%">
            <el-option v-for="p in parties" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="发票号码" required>
          <el-input v-model="invoiceNo" placeholder="票面右上角号码" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="发票代码">
          <el-input v-model="invoiceCode" placeholder="电子发票常无" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="票种">
          <el-select v-model="invoiceType" clearable style="width: 100%">
            <el-option v-for="t in invoiceTypes" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="开票日期">
          <el-date-picker v-model="invoiceDate" type="date" value-format="YYYY-MM-DD"
                          placeholder="选择日期" style="width: 100%" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="税率（%）">
          <el-input-number v-model="taxRate" :min="0" :precision="2" :controls="false"
                           style="width: 100%" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="认证状态">
          <el-select v-model="authStatus" style="width: 100%">
            <el-option label="待认证" value="pending" />
            <el-option label="已认证" value="verified" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="8">
        <el-form-item label="不含税金额">
          <el-input-number v-model="amount" :min="0" :precision="2" :controls="false"
                           style="width: 100%" />
        </el-form-item>
      </el-col>
      <el-col :span="8">
        <el-form-item label="税额">
          <el-input-number v-model="taxAmount" :min="0" :precision="2" :controls="false"
                           style="width: 100%" />
        </el-form-item>
      </el-col>
      <el-col :span="8">
        <el-form-item label="价税合计" required>
          <el-input-number v-model="totalAmount" :min="0" :precision="2" :controls="false"
                           style="width: 100%" />
        </el-form-item>
      </el-col>
    </template>

    <template #items="{ readonly }">
      <AllocationTable v-model="allocations" :targets="targets" :options="orders"
                       :readonly="readonly" show-tax :total-amount="totalAmount" />
    </template>
  </DocFormPage>
</template>
