<script setup lang="ts">
/**
 * 销售申请单表单（T-V2-29）：表头 + 行项 + 保存草稿 / 保存并提交。
 *
 * 表头结构：单据日期、关联合同、经办人（通用）+ 客户（档案 / 文本二选一）、期望交期、销售部门（特有）。
 */
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import ContractDetailDrawer from '@/components/doc/ContractDetailDrawer.vue'
import DocFormPage from '@/components/doc/DocFormPage.vue'
import { fetchContract, fetchMasterOptions, type Dict } from '@/api'

const extra = ref<Dict>({
  customer_id: null,
  customer_name_text: '',
  sales_dept_id: null,
  expect_delivery_date: null,
})

const customers = ref<Dict[]>([])
const orgs = ref<Dict[]>([])
/** 关联合同后的只读详情抽屉（与采购申请单同构） */
const drawer = ref<InstanceType<typeof ContractDetailDrawer> | null>(null)

/** 客户下拉（懒加载一次） */
async function ensureCustomers() {
  if (customers.value.length) return
  try {
    customers.value = await fetchMasterOptions('customer')
  } catch {
    customers.value = []
  }
}
void ensureCustomers()

/** 组织（部门）下拉：来自 /api/master/options/org */
async function ensureOrgs() {
  if (orgs.value.length) return
  try {
    orgs.value = await fetchMasterOptions('org')
  } catch {
    orgs.value = []
  }
}
void ensureOrgs()

const customerId = computed({
  get: () => (extra.value.customer_id as number | null) ?? null,
  set: (v: number | null) => { extra.value = { ...extra.value, customer_id: v } },
})
const customerText = computed({
  get: () => (extra.value.customer_name_text as string) ?? '',
  set: (v: string) => { extra.value = { ...extra.value, customer_name_text: v } },
})
const expectDate = computed({
  get: () => (extra.value.expect_delivery_date as string | null) ?? null,
  set: (v: string | null) => { extra.value = { ...extra.value, expect_delivery_date: v } },
})
const deptId = computed({
  get: () => (extra.value.sales_dept_id as number | null) ?? null,
  set: (v: number | null) => { extra.value = { ...extra.value, sales_dept_id: v } },
})
const customerName = computed(() => {
  const hit = customers.value.find((c) => c.id === customerId.value)
  return hit ? `${hit.name}（${hit.code}）` : '—'
})

// ---------------- 提取销售合同明细（与采购申请单 V2.1/N2 同构） ----------------
const extracting = ref(false)

/**
 * 把关联**销售合同**的行项提取为本单明细（草稿值，可修改）。
 *
 * 与采购侧的差别只在合同数据源（DocFormPage 的 contract-source="sales"
 * 已把关联合同下拉限定为销售类合同），行项结构 / 提取约束完全一致：
 * - 合同行项必须已绑定物料（product_id），未绑定的行后端会拒绝；
 * - 单内已有行项时先二次确认再覆盖。
 */
async function extractFromContract(header: Dict, items: Record<string, any>[]) {
  const contractId = header?.contract_id
  if (!contractId) {
    ElMessage.warning('请先选择关联合同')
    return
  }
  extracting.value = true
  try {
    const contract = await fetchContract(Number(contractId))
    const rows = (contract.items || []) as Dict[]
    if (!rows.length) {
      ElMessage.warning('该合同没有行项，无法提取')
      return
    }
    const unbound = rows.filter((r) => !r.product_id).length
    if (unbound) {
      ElMessage.warning(`该合同有 ${unbound} 行未绑定物料，请先在合同台账补齐后再提取`)
      return
    }
    if (items.length) {
      try {
        await ElMessageBox.confirm(
          `当前已有 ${items.length} 行，提取将覆盖这些行项。是否继续？`,
          '确认覆盖', { type: 'warning', confirmButtonText: '覆盖', cancelButtonText: '取消' },
        )
      } catch {
        return
      }
    }
    items.splice(0, items.length)
    for (const r of rows) {
      items.push({
        product_id: r.product_id,
        product_code: r.product_code ?? '',
        product_name: r.product_name ?? '',
        spec: r.spec ?? null,
        qty: Number(r.qty) || 0,
        unit_price: Number(r.unit_price) || 0,
        warehouse_id: null,
        remark: r.remark ?? '',
      })
    }
    ElMessage.success(`已提取 ${rows.length} 行合同明细，可继续调整数量与单价`)
  } catch {
    // 拦截器已提示
  } finally {
    extracting.value = false
  }
}
</script>

<template>
  <DocFormPage v-model="extra" title="销售申请单" kind-label="销售申请单"
               api="/api/sales/requests" perm-prefix="sales.request"
               list-route="sales-requests" show-warehouse show-subject contract-source="sales"
               :extra-cols="['ordered']">
    <template #header>
      <el-col :span="12">
        <el-form-item label="客户">
          <el-select v-model="customerId" filterable clearable placeholder="选择客户档案（可留空）"
                     style="width: 100%" @visible-change="ensureCustomers">
            <el-option v-for="c in customers" :key="c.id" :label="`${c.name}（${c.code}）`" :value="c.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="客户文本">
          <el-input v-model="customerText" placeholder="未建档客户可只填名称"
                    :disabled="!!customerId" maxlength="100" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="客户快照">
          <span class="gray">{{ customerName }}</span>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="期望交期">
          <el-date-picker v-model="expectDate" type="date" value-format="YYYY-MM-DD"
                          placeholder="希望交付日期" style="width: 100%" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="销售部门">
          <el-select v-model="deptId" filterable clearable placeholder="选择部门（可留空）"
                     style="width: 100%">
            <el-option v-for="o in orgs" :key="o.id" :label="o.name" :value="o.id" />
          </el-select>
        </el-form-item>
      </el-col>
    </template>

    <!-- 与采购申请单同构：关联销售合同后，可在不离开本单的前提下核对合同详情 -->
    <template #contract-actions="{ header }">
      <el-button size="small" :disabled="!header.contract_id"
                 @click="drawer?.open(header.contract_id)">查看合同详情</el-button>
      <span v-if="!header.contract_id" class="gray">请先选择关联合同</span>
    </template>

    <!-- 提取关联销售合同的行项为本单明细（草稿值，可修改）；未选合同时禁用 -->
    <template #items-toolbar="{ header, items, editable }">
      <el-button v-if="editable" size="small" type="primary" plain
                 :disabled="!header.contract_id" :loading="extracting"
                 @click="extractFromContract(header, items)">
        提取合同明细
      </el-button>
    </template>
  </DocFormPage>

  <ContractDetailDrawer ref="drawer" />
</template>

<style scoped>
.gray { color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); }
</style>
