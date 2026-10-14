<script setup lang="ts">
/**
 * 付款单表单（V2.5，AC-V2.5-01/14）。
 *
 * 从采购单列表「更多 → 发起付款单」进入时带 `?source_type=purchase_order&source_id=<id>`：
 * 预填供应商、金额（= **未付金额**）与一行核销明细，并把该采购单塞进下拉候选
 * （它可能不在"最近 200 张已审核采购单"里）。预填只是默认值，财务可改成部分付款。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AllocationTable from '@/components/doc/AllocationTable.vue'
import DocFormPage from '@/components/doc/DocFormPage.vue'
import { fetchDoc, fetchDocList, fetchFinanceMeta, fetchMasterOptions, fetchSubjects, type Dict } from '@/api'
import type { AllocationRow } from '@/types/doc'

const route = useRoute()
const formRef = ref<InstanceType<typeof DocFormPage> | null>(null)

const suppliers = ref<Dict[]>([])
/** V2.6：我方公司字典（含开户行等扩展属性），供签约公司 → 我方开户行自动填充 */
const subjects = ref<Dict[]>([])
const settleTypes = ref<string[]>([])
const orders = ref<Dict[]>([{ id: 0, doc_no: '', total_amount: 0 }].slice(1))
const allocations = ref<AllocationRow[]>([])
const extra = ref<Dict>({})
const partyId = ref<number | null>(null)
const settleType = ref<string>('')
const payAccount = ref<string>('')
const totalAmount = ref<number>(0)
/**
 * 《付款申请单》纸质模板字段（V2.5）。
 * 放在一个对象里而不是 9 个 ref：`sync()` 只需展开一次，表单模板也只需一组 el-input。
 */
const payFields = reactive<Record<string, string>>({
  payee_bank: '', payee_account: '', payer_bank: '', category_l1: '', category_l2: '',
  belong_period: '', bank_purpose: '', pay_reason: '', plan_type: '计划内',
})
const CATEGORY_L1 = ['经营', '经济', '行政', '人力', '投资', '往来']

// ---------------- V2.6：选供应商 / 签约公司后自动填充银行信息 ----------------
/**
 * 取舍：**"选择那一刻、仅空值填充"** —— 下拉变更或签约公司变更时，只往空字段写入
 * 档案值；用户已手改（非空）的一律不覆盖。这样既省录入，又不会在用户清空重填时
 * 被档案值反复顶回来；编辑已保存单据回填时也不会破坏落库值（回填发生在 watch 前）。
 */

/** 选择供应商 → 收款方开户银行 / 账号（档案有值才填，仅空字段） */
function onSupplierChange(id: number | null) {
  if (!id) return
  const hit = suppliers.value.find((s) => s.id === id)
  if (!hit) return
  if (!payFields.payee_bank && hit.bank_name) payFields.payee_bank = String(hit.bank_name)
  if (!payFields.payee_account && hit.bank_account) payFields.payee_account = String(hit.bank_account)
}

/** 选择签约公司 → 我方开户行（我方公司字典的 bank_name，仅空字段） */
function onSubjectChange(code: string | null) {
  if (!code) return
  const hit = subjects.value.find((s) => s.code === code)
  if (hit && !payFields.payer_bank && hit.bank_name) {
    payFields.payer_bank = String(hit.bank_name)
  }
}

const TARGETS = [{ code: 'purchase_order', label: '采购单' }]

/** 把UI状态同步进 DocFormPage 的扩展字段（保存时原样提交给后端） */
function sync() {
  extra.value = {
    supplier_id: partyId.value || null,
    settle_type: settleType.value || null,
    pay_account: payAccount.value || null,
    total_amount: Number(totalAmount.value || 0),
    ...payFields,
    allocations: allocations.value.map((r) => ({
      target_type: r.target_type,
      target_id: r.target_id,
      amount: Number(r.amount || 0),
      remark: r.remark || null,
    })),
  }
}
watch([partyId, settleType, payAccount, totalAmount, allocations, payFields], sync,
      { deep: true })

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
  try {
    subjects.value = await fetchSubjects()
  } catch {
    subjects.value = []
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

/** 签约公司由 DocFormPage 内部表头维护：监听其变化触发我方开户行自动填充 */
watch(() => formRef.value?.header?.subject_code, (code) => onSubjectChange((code as string) || null))

/** 编辑已保存单据：把落库值填回表单（详情由 DocFormPage 异步加载） */
watch(() => formRef.value?.detail, (detail: Dict | null | undefined) => {
  if (!detail || !detail.id || allocations.value.length) return
  partyId.value = (detail.supplier_id as number) || null
  settleType.value = (detail.settle_type as string) || ''
  payAccount.value = (detail.pay_account as string) || ''
  totalAmount.value = Number(detail.total_amount || 0)
  for (const key of Object.keys(payFields)) {
    payFields[key] = (detail[key] as string) || (key === 'plan_type' ? '计划内' : '')
  }
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
          <el-select v-model="partyId" filterable placeholder="选择供应商" style="width: 100%"
                     @change="(v: number | null) => onSupplierChange(v)">
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

      <!-- V2.5：《付款申请单》纸质模板字段（打印模板可直接引用，见 docs/33） -->
      <el-col :span="12">
        <el-form-item label="收款方开户银行">
          <el-input v-model="payFields.payee_bank" placeholder="如 中国建设银行…支行" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="收款方账号">
          <el-input v-model="payFields.payee_account" placeholder="如 1405 0183 …" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="我方开户行">
          <el-input v-model="payFields.payer_bank" placeholder="如 中国银行…支行" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="一级分类">
          <el-select v-model="payFields.category_l1" clearable placeholder="经营/经济/行政…"
                     style="width: 100%">
            <el-option v-for="c in CATEGORY_L1" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="二级分类">
          <el-input v-model="payFields.category_l2" placeholder="写明具体费用" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="付款归属期">
          <el-input v-model="payFields.belong_period" placeholder="如 2026-09 / 以前年度" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="银行付款用途">
          <el-input v-model="payFields.bank_purpose" placeholder="如 预付款 / 代付款" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="计划内/外">
          <el-select v-model="payFields.plan_type" style="width: 100%">
            <el-option label="计划内" value="计划内" />
            <el-option label="计划外" value="计划外" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="24">
        <el-form-item label="付款事由">
          <el-input v-model="payFields.pay_reason" placeholder="与备注分开填：本笔付款的具体事由" />
        </el-form-item>
      </el-col>
    </template>

    <template #items="{ readonly }">
      <AllocationTable v-model="allocations" :targets="TARGETS" :options="orders"
                       :readonly="readonly" :single-row="false" :total-amount="totalAmount" />
    </template>
  </DocFormPage>
</template>
