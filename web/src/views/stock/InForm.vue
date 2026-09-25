<script setup lang="ts">
/**
 * 入库单表单（T-V2-25）：审核即过账。
 *
 * 由采购单下推生成时：仓库 / 入库类型 / 供应商 / 行项数量已预填，
 * 单价沿用采购单价（只读），可在保存前调整入库数量。
 */
import { ref } from 'vue'

import DocFormPage from '@/components/doc/DocFormPage.vue'
import { fetchMasterOptions, type Dict } from '@/api'

const extra = ref<Dict>({
  warehouse_id: null,
  in_type: '采购入库',
  supplier_id: null,
})

const IN_TYPES = ['采购入库', '退货入库', '其他入库']
const warehouses = ref<Dict[]>([])
const suppliers = ref<Dict[]>([])

async function ensureOptions() {
  const tasks: Promise<void>[] = []
  if (!warehouses.value.length) {
    tasks.push(fetchMasterOptions('warehouse').then((v) => { warehouses.value = v }).catch(() => { warehouses.value = [] }))
  }
  if (!suppliers.value.length) {
    tasks.push(fetchMasterOptions('supplier').then((v) => { suppliers.value = v }).catch(() => { suppliers.value = [] }))
  }
  await Promise.all(tasks)
}
void ensureOptions()
</script>

<template>
  <DocFormPage v-model="extra" title="入库单" kind-label="入库单"
               api="/api/stock/in-orders" perm-prefix="stock.in"
               list-route="stock-in-orders" show-warehouse :show-price="false"
               :extra-cols="['received']"
               :extra-required="[{ key: 'warehouse_id', label: '入库仓库' }]">
    <template #header>
      <el-col :span="12">
        <el-form-item label="入库仓库" required>
          <el-select v-model="extra.warehouse_id" filterable placeholder="请选择仓库"
                     style="width: 100%" @visible-change="ensureOptions">
            <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="入库类型" required>
          <el-select v-model="extra.in_type" style="width: 100%">
            <el-option v-for="t in IN_TYPES" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="供应商">
          <el-select v-model="extra.supplier_id" filterable clearable allow-create
                     placeholder="采购入库建议填写" style="width: 100%" @visible-change="ensureOptions">
            <el-option v-for="s in suppliers" :key="s.id" :label="`${s.name}（${s.code}）`" :value="s.id" />
          </el-select>
        </el-form-item>
      </el-col>
    </template>
  </DocFormPage>
</template>
