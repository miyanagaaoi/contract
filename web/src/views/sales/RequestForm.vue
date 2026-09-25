<script setup lang="ts">
/**
 * 销售申请单表单（T-V2-29）：表头 + 行项 + 保存草稿 / 保存并提交。
 *
 * 表头结构：单据日期、关联合同、经办人（通用）+ 客户（档案 / 文本二选一）、期望交期、销售部门（特有）。
 */
import { computed, ref } from 'vue'

import DocFormPage from '@/components/doc/DocFormPage.vue'
import { fetchMasterOptions, type Dict } from '@/api'

const extra = ref<Dict>({
  customer_id: null,
  customer_name_text: '',
  sales_dept_id: null,
  expect_delivery_date: null,
})

const customers = ref<Dict[]>([])

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
</script>

<template>
  <DocFormPage v-model="extra" title="销售申请单" kind-label="销售申请单"
               api="/api/sales/requests" perm-prefix="sales.request"
               list-route="sales-requests" show-warehouse contract-source="sales"
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
          <el-input-number v-model="deptId" :min="1" :controls="false"
                           placeholder="部门 ID（可留空）" style="width: 100%" />
        </el-form-item>
      </el-col>
    </template>
  </DocFormPage>
</template>

<style scoped>
.gray { color: #909399; font-size: 12.5px; }
</style>
