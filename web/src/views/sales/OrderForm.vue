<script setup lang="ts">
/**
 * 销售订单表单（T-V2-30）：表头 + 行项 + 保存草稿 / 保存并提交。
 *
 * 特有表头：客户（必填）、销售部门、交货日期、收货地址、联系人 / 电话、发运仓库、币种。
 * 由销售申请单下推生成时，客户与行项已预填，价格取申请单快照。
 */
import { ref } from 'vue'

import DocFormPage from '@/components/doc/DocFormPage.vue'
import { fetchMasterOptions, type Dict } from '@/api'

const extra = ref<Dict>({
  customer_id: null,
  sales_dept_id: null,
  delivery_date: null,
  delivery_address: '',
  contact_name: '',
  contact_phone: '',
  ship_warehouse_id: null,
  currency: 'CNY',
})

const customers = ref<Dict[]>([])
const warehouses = ref<Dict[]>([])

const CURRENCIES = ['CNY', 'USD', 'EUR', 'HKD']

async function ensureOptions() {
  const tasks: Promise<void>[] = []
  if (!customers.value.length) {
    tasks.push(fetchMasterOptions('customer').then((v) => { customers.value = v }).catch(() => { customers.value = [] }))
  }
  if (!warehouses.value.length) {
    tasks.push(fetchMasterOptions('warehouse').then((v) => { warehouses.value = v }).catch(() => { warehouses.value = [] }))
  }
  await Promise.all(tasks)
}
void ensureOptions()
</script>

<template>
  <DocFormPage v-model="extra" title="销售订单" kind-label="销售订单"
               api="/api/sales/orders" perm-prefix="sales.order"
               list-route="sales-orders" show-warehouse contract-source="sales"
               :extra-cols="['shipped']"
               :extra-required="[{ key: 'customer_id', label: '客户' }]">
    <template #header>
      <el-col :span="12">
        <el-form-item label="客户" required>
          <el-select v-model="extra.customer_id" filterable placeholder="请选择客户"
                     style="width: 100%" @visible-change="ensureOptions">
            <el-option v-for="c in customers" :key="c.id" :label="`${c.name}（${c.code}）`" :value="c.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="交货日期">
          <el-date-picker v-model="extra.delivery_date" type="date" value-format="YYYY-MM-DD"
                          style="width: 100%" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="联系人">
          <el-input v-model="extra.contact_name" maxlength="50" placeholder="收货联系人" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="联系电话">
          <el-input v-model="extra.contact_phone" maxlength="30" placeholder="收货联系电话" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="发运仓库">
          <el-select v-model="extra.ship_warehouse_id" filterable clearable
                     placeholder="默认发货仓库（可留空）" style="width: 100%" @visible-change="ensureOptions">
            <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="币种">
          <el-select v-model="extra.currency" filterable allow-create style="width: 100%">
            <el-option v-for="c in CURRENCIES" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="销售部门">
          <el-input-number v-model="extra.sales_dept_id" :min="1" :controls="false"
                           placeholder="部门 ID（可留空）" style="width: 100%" />
        </el-form-item>
      </el-col>
      <el-col :span="24">
        <el-form-item label="收货地址">
          <el-input v-model="extra.delivery_address" maxlength="200" placeholder="收货详细地址" />
        </el-form-item>
      </el-col>
    </template>
  </DocFormPage>
</template>
