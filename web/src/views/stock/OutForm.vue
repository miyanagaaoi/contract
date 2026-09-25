<script setup lang="ts">
/**
 * 出库单表单（T-V2-25）：审核即过账（负库存拦截）。
 *
 * 由销售订单下推生成时：仓库 / 出库类型 / 客户 / 行项数量已预填，
 * 单价沿用销售单价（只读），可在保存前调整出库数量。
 */
import { ref } from 'vue'

import DocFormPage from '@/components/doc/DocFormPage.vue'
import { fetchMasterOptions, type Dict } from '@/api'

const extra = ref<Dict>({
  warehouse_id: null,
  out_type: '销售出库',
  customer_id: null,
})

const OUT_TYPES = ['销售出库', '领用出库', '其他出库']
const warehouses = ref<Dict[]>([])
const customers = ref<Dict[]>([])

async function ensureOptions() {
  const tasks: Promise<void>[] = []
  if (!warehouses.value.length) {
    tasks.push(fetchMasterOptions('warehouse').then((v) => { warehouses.value = v }).catch(() => { warehouses.value = [] }))
  }
  if (!customers.value.length) {
    tasks.push(fetchMasterOptions('customer').then((v) => { customers.value = v }).catch(() => { customers.value = [] }))
  }
  await Promise.all(tasks)
}
void ensureOptions()
</script>

<template>
  <DocFormPage v-model="extra" title="出库单" kind-label="出库单"
               api="/api/stock/out-orders" perm-prefix="stock.out"
               list-route="stock-out-orders" show-warehouse :show-price="false"
               :extra-cols="['shipped']"
               :extra-required="[{ key: 'warehouse_id', label: '出库仓库' }]">
    <template #header>
      <el-col :span="12">
        <el-form-item label="出库仓库" required>
          <el-select v-model="extra.warehouse_id" filterable placeholder="请选择仓库"
                     style="width: 100%" @visible-change="ensureOptions">
            <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="出库类型" required>
          <el-select v-model="extra.out_type" style="width: 100%">
            <el-option v-for="t in OUT_TYPES" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="客户">
          <el-select v-model="extra.customer_id" filterable clearable
                     placeholder="销售出库建议填写" style="width: 100%" @visible-change="ensureOptions">
            <el-option v-for="c in customers" :key="c.id" :label="`${c.name}（${c.code}）`" :value="c.id" />
          </el-select>
        </el-form-item>
      </el-col>
    </template>
  </DocFormPage>
</template>
