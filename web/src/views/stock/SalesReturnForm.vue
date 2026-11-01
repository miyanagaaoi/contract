<script setup lang="ts">
/**
 * 销售退货单表单（CR-034）：选择销售订单 → 带入未发数量 → 入库过账并回冲已发数量。
 */
import { ref } from 'vue'

import DocFormPage from '@/components/doc/DocFormPage.vue'
import { fetchMasterOptions, http, type Dict } from '@/api'

const formRef = ref<InstanceType<typeof DocFormPage> | null>(null)
const extra = ref<Dict>({
  warehouse_id: null, customer_id: null,
  source_doc_type: 'sales_order', source_doc_id: null, source_doc_no: null,
})
const warehouses = ref<Dict[]>([])
const customers = ref<Dict[]>([])
const orders = ref<Dict[]>([])
const loadingOrders = ref(false)

async function ensureOptions() {
  try {
    if (!warehouses.value.length) warehouses.value = await fetchMasterOptions('warehouse')
    if (!customers.value.length) customers.value = await fetchMasterOptions('customer')
    if (!orders.value.length) {
      loadingOrders.value = true
      const { data } = await http.get('/sales/orders', { params: { page_size: 100 } })
      orders.value = (data.items || []).filter((d: Dict) => ['approved', 'submitted'].includes(d.status))
    }
  } catch { /* 拦截器已提示 */ } finally {
    loadingOrders.value = false
  }
}
void ensureOptions()

async function onSourceChange(id: number | null) {
  extra.value.source_doc_id = id || null
  extra.value.source_doc_no = (orders.value.find((o) => o.id === id)?.doc_no) as string || null
  extra.value.customer_id = (orders.value.find((o) => o.id === id)?.customer_id) as number || extra.value.customer_id
  if (!id) return
  try {
    const { data } = await http.get(`/sales/orders/${id}`)
    const rows = (data.items || []).map((it: Dict) => ({
      product_id: it.product_id,
      qty: Math.max(0, Number(it.qty || 0) - Number(it.shipped_qty || 0)),
      unit_price: Number(it.unit_price || 0),
      src_item_id: it.id,
    })).filter((r: Dict) => r.qty > 0)
    const arr = formRef.value?.items as Dict[] | undefined
    if (arr) arr.splice(0, arr.length, ...rows)
  } catch { /* 拦截器已提示 */ }
}
</script>

<template>
  <DocFormPage ref="formRef" v-model="extra" title="销售退货单" kind-label="销售退货单"
               api="/api/stock/sales-returns" perm-prefix="stock.in"
               list-route="stock-sales-returns" show-subject show-warehouse
               :extra-required="[{ key: 'warehouse_id', label: '入库仓库' }]">
    <template #header>
      <el-col :span="8">
        <el-form-item label="入库仓库" required>
          <el-select v-model="extra.warehouse_id" filterable placeholder="请选择仓库"
                     style="width: 100%" @visible-change="ensureOptions">
            <el-option v-for="w in warehouses" :key="w.id"
                       :label="(w.display_name as string) || w.name" :value="w.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="8">
        <el-form-item label="客户">
          <el-select v-model="extra.customer_id" filterable clearable placeholder="可选"
                     style="width: 100%" @visible-change="ensureOptions">
            <el-option v-for="c in customers" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="8">
        <el-form-item label="来源销售订单">
          <el-select v-model="extra.source_doc_id" filterable clearable
                     :loading="loadingOrders" placeholder="选择后自动带入未发数量"
                     style="width: 100%" @visible-change="ensureOptions"
                     @change="onSourceChange">
            <el-option v-for="o in orders" :key="o.id"
                       :label="`${o.doc_no}（${o.customer_name || '—'}）`" :value="o.id" />
          </el-select>
        </el-form-item>
      </el-col>
    </template>
  </DocFormPage>
</template>
