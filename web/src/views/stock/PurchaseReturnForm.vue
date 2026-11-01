<script setup lang="ts">
/**
 * 采购退货单表单（CR-034）：选择采购单 → 带入未收数量 → 出库过账并回冲已收数量。
 */
import { ref } from 'vue'

import DocFormPage from '@/components/doc/DocFormPage.vue'
import { fetchMasterOptions, http, type Dict } from '@/api'

const formRef = ref<InstanceType<typeof DocFormPage> | null>(null)
const extra = ref<Dict>({
  warehouse_id: null, supplier_id: null,
  source_doc_type: 'purchase_order', source_doc_id: null, source_doc_no: null,
})
const warehouses = ref<Dict[]>([])
const suppliers = ref<Dict[]>([])
const orders = ref<Dict[]>([])
const loadingOrders = ref(false)

async function ensureOptions() {
  try {
    if (!warehouses.value.length) warehouses.value = await fetchMasterOptions('warehouse')
    if (!suppliers.value.length) suppliers.value = await fetchMasterOptions('supplier')
    if (!orders.value.length) {
      loadingOrders.value = true
      const { data } = await http.get('/purchase/orders', { params: { page_size: 100 } })
      orders.value = (data.items || []).filter((d: Dict) => ['approved', 'submitted'].includes(d.status))
    }
  } catch { /* 拦截器已提示 */ } finally {
    loadingOrders.value = false
  }
}
void ensureOptions()

/** 选择采购单：落来源单号快照，并按「未收数量」带入行项 */
async function onSourceChange(id: number | null) {
  extra.value.source_doc_id = id || null
  extra.value.source_doc_no = (orders.value.find((o) => o.id === id)?.doc_no) as string || null
  extra.value.supplier_id = (orders.value.find((o) => o.id === id)?.supplier_id) as number || extra.value.supplier_id
  if (!id) return
  try {
    const { data } = await http.get(`/purchase/orders/${id}`)
    const rows = (data.items || []).map((it: Dict) => ({
      product_id: it.product_id,
      qty: Math.max(0, Number(it.qty || 0) - Number(it.received_qty || 0)),
      unit_price: Number(it.unit_price || 0),
      src_item_id: it.id,
    })).filter((r: Dict) => r.qty > 0)
    const arr = formRef.value?.items as Dict[] | undefined
    if (arr) arr.splice(0, arr.length, ...rows)
  } catch { /* 拦截器已提示 */ }
}
</script>

<template>
  <DocFormPage ref="formRef" v-model="extra" title="采购退货单" kind-label="采购退货单"
               api="/api/stock/purchase-returns" perm-prefix="stock.out"
               list-route="stock-purchase-returns" show-subject show-warehouse
               :extra-required="[{ key: 'warehouse_id', label: '退货仓库' }]">
    <template #header>
      <el-col :span="8">
        <el-form-item label="退货仓库" required>
          <el-select v-model="extra.warehouse_id" filterable placeholder="请选择仓库"
                     style="width: 100%" @visible-change="ensureOptions">
            <el-option v-for="w in warehouses" :key="w.id"
                       :label="(w.display_name as string) || w.name" :value="w.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="8">
        <el-form-item label="供应商">
          <el-select v-model="extra.supplier_id" filterable clearable placeholder="可选"
                     style="width: 100%" @visible-change="ensureOptions">
            <el-option v-for="s in suppliers" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="8">
        <el-form-item label="来源采购单">
          <el-select v-model="extra.source_doc_id" filterable clearable
                     :loading="loadingOrders" placeholder="选择后自动带入未收数量"
                     style="width: 100%" @visible-change="ensureOptions"
                     @change="onSourceChange">
            <el-option v-for="o in orders" :key="o.id"
                       :label="`${o.doc_no}（${o.supplier_name || '—'}）`" :value="o.id" />
          </el-select>
        </el-form-item>
      </el-col>
    </template>
  </DocFormPage>
</template>
