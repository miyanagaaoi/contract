<script setup lang="ts">
/**
 * 采购申请单表单（T-V2-24）：表头 + 行项 + 保存草稿 / 保存并提交。
 *
 * 表头结构：单据日期、关联合同、经办人（通用）+ 需求日期、申请部门、建议供应商、用途说明（特有）。
 */
import { computed, ref } from 'vue'

import DocFormPage from '@/components/doc/DocFormPage.vue'
import { fetchMasterOptions, type Dict } from '@/api'

const extra = ref<Dict>({
  request_dept_id: null,
  need_date: null,
  purpose: '',
  suggest_supplier_id: null,
})

const suppliers = ref<Dict[]>([])

/** 建议供应商下拉（懒加载一次） */
async function ensureSuppliers() {
  if (suppliers.value.length) return
  try {
    suppliers.value = await fetchMasterOptions('supplier')
  } catch {
    suppliers.value = []
  }
}
void ensureSuppliers()

const purpose = computed({
  get: () => (extra.value.purpose as string) ?? '',
  set: (v: string) => { extra.value = { ...extra.value, purpose: v } },
})
const needDate = computed({
  get: () => (extra.value.need_date as string | null) ?? null,
  set: (v: string | null) => { extra.value = { ...extra.value, need_date: v } },
})
const deptId = computed({
  get: () => (extra.value.request_dept_id as number | null) ?? null,
  set: (v: number | null) => { extra.value = { ...extra.value, request_dept_id: v } },
})
const suggestSupplierId = computed({
  get: () => (extra.value.suggest_supplier_id as number | null) ?? null,
  set: (v: number | null) => { extra.value = { ...extra.value, suggest_supplier_id: v } },
})
const suggestSupplierName = computed(() => {
  const hit = suppliers.value.find((s) => s.id === suggestSupplierId.value)
  return hit ? `${hit.name}（${hit.code}）` : '—'
})
</script>

<template>
  <DocFormPage v-model="extra" title="采购申请单" kind-label="采购申请单"
               api="/api/purchase/requests" perm-prefix="purchase.request"
               list-route="purchase-requests" show-warehouse :extra-cols="['ordered']">
    <template #header>
      <el-col :span="12">
        <el-form-item label="需求日期">
          <el-date-picker v-model="needDate" type="date" value-format="YYYY-MM-DD"
                          placeholder="期望到货/使用日期" style="width: 100%" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="申请部门">
          <el-input-number v-model="deptId" :min="1" :controls="false"
                           placeholder="部门 ID（可留空）" style="width: 100%" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="建议供应商">
          <el-select v-model="suggestSupplierId" filterable clearable placeholder="仅作建议，可留空"
                     style="width: 100%" @visible-change="ensureSuppliers">
            <el-option v-for="s in suppliers" :key="s.id" :label="`${s.name}（${s.code}）`" :value="s.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="建议供应商快照">
          <span class="gray">{{ suggestSupplierName }}</span>
        </el-form-item>
      </el-col>
      <el-col :span="24">
        <el-form-item label="用途说明">
          <el-input v-model="purpose" type="textarea" :rows="2" maxlength="200" show-word-limit
                    placeholder="本次采购的用途 / 背景" />
        </el-form-item>
      </el-col>
    </template>
  </DocFormPage>
</template>

<style scoped>
.gray { color: #909399; font-size: 12.5px; }
</style>
