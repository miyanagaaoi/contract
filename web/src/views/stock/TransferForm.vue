<script setup lang="ts">
/**
 * 调拨单表单（V2.1 / N13）。
 *
 * 调出仓 / 调入仓均必填且**不得相同**（前后端双重校验：后端见
 * `app/routers/stock.py::_apply_transfer_fields`，防止绕过前端）。
 * 调拨不涉及金额，故行项隐藏单价列。
 */
import { ref } from 'vue'

import DocFormPage from '@/components/doc/DocFormPage.vue'
import { fetchMasterOptions, type Dict } from '@/api'

const extra = ref<Dict>({
  from_warehouse_id: null,
  to_warehouse_id: null,
})

const warehouses = ref<Dict[]>([])

async function ensureOptions() {
  if (warehouses.value.length) return
  try {
    warehouses.value = await fetchMasterOptions('warehouse')
  } catch {
    warehouses.value = []
  }
}
void ensureOptions()
</script>

<template>
  <DocFormPage v-model="extra" title="调拨单" kind-label="调拨单"
               api="/api/stock/transfers" perm-prefix="stock.transfer"
               list-route="stock-transfer-list" :show-price="false"
               :extra-required="[{ key: 'from_warehouse_id', label: '调出仓库' },
                                 { key: 'to_warehouse_id', label: '调入仓库' }]">
    <template #header>
      <el-col :span="12">
        <el-form-item label="调出仓库" required>
          <el-select v-model="extra.from_warehouse_id" filterable placeholder="请选择调出仓库"
                     style="width: 100%" @visible-change="ensureOptions">
            <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="调入仓库" required>
          <el-select v-model="extra.to_warehouse_id" filterable placeholder="请选择调入仓库"
                     style="width: 100%" @visible-change="ensureOptions">
            <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="24">
        <el-alert type="info" :closable="false" show-icon
                  title="审核后将在同一事务内完成：调出仓减少、调入仓增加；调出仓结存不足会被拦截。" />
      </el-col>
    </template>
  </DocFormPage>
</template>
