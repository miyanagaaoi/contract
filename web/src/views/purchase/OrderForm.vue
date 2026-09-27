<script setup lang="ts">
/**
 * 采购单表单（T-V2-24）：表头 + 行项 + 保存草稿 / 保存并提交。
 *
 * 特有表头：供应商（必填）、预计到货日期、结算方式、币种、收货仓库、采购部门。
 * 由采购申请单下推生成时，供应商/收货仓库已预填，价格取申请单快照。
 */
import { ref } from 'vue'

import DocFormPage from '@/components/doc/DocFormPage.vue'
import SupplierDetailDialog from '@/components/SupplierDetailDialog.vue'
import { fetchMasterOptions, type Dict } from '@/api'

const extra = ref<Dict>({
  supplier_id: null,
  expected_arrival_date: null,
  settle_type: '',
  currency: 'CNY',
  receipt_warehouse_id: null,
  purchase_dept_id: null,
})

const suppliers = ref<Dict[]>([])
const warehouses = ref<Dict[]>([])
const orgs = ref<Dict[]>([])

const SETTLE_TYPES = ['月结', '现结', '货到付款', '预付款', '其他']
const CURRENCIES = ['CNY', 'USD', 'EUR', 'HKD']

async function ensureOptions() {
  const tasks: Promise<void>[] = []
  if (!suppliers.value.length) {
    tasks.push(fetchMasterOptions('supplier').then((v) => { suppliers.value = v }).catch(() => { suppliers.value = [] }))
  }
  if (!warehouses.value.length) {
    tasks.push(fetchMasterOptions('warehouse').then((v) => { warehouses.value = v }).catch(() => { warehouses.value = [] }))
  }
  if (!orgs.value.length) {
    tasks.push(fetchMasterOptions('org').then((v) => { orgs.value = v }).catch(() => { orgs.value = [] }))
  }
  await Promise.all(tasks)
}
void ensureOptions()

/**
 * V2.2：供货商**默认显示简称**（下单、对账、口头沟通都用简称）。
 * 下拉面板把全称作为次要说明补在简称后面，避免两家供货商简称相近时选错。
 */
function supplierLabel(s: Dict): string {
  return (s.short_name as string) || (s.name as string) || ''
}

/** V2.2：供货商详情弹窗（只读，不离开当前单据） */
const supplierDialog = ref<InstanceType<typeof SupplierDetailDialog> | null>(null)

function openSupplier(id: number | null | undefined) {
  if (!id) return
  supplierDialog.value?.open(id)
}
</script>

<template>
  <DocFormPage v-model="extra" title="采购单" kind-label="采购单"
               api="/api/purchase/orders" perm-prefix="purchase.order"
               list-route="purchase-orders" show-warehouse :extra-cols="['received']">
    <template #header>
      <el-col :span="12">
        <el-form-item label="供应商" required>
          <!-- V2.2：下拉显示简称；右侧按钮点开只读供货商档案，不必跳去资料库 -->
          <div class="field-with-action">
            <el-select v-model="extra.supplier_id" filterable placeholder="请选择供应商"
                       @visible-change="ensureOptions">
              <el-option v-for="s in suppliers" :key="s.id"
                         :label="supplierLabel(s)" :value="s.id">
                <span>{{ supplierLabel(s) }}</span>
                <span v-if="s.short_name && s.short_name !== s.name" class="opt-sub">{{ s.name }}</span>
              </el-option>
            </el-select>
            <el-button size="small" :disabled="!extra.supplier_id"
                       @click="openSupplier(extra.supplier_id as number | null)">供货商详情</el-button>
          </div>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="预计到货">
          <el-date-picker v-model="extra.expected_arrival_date" type="date" value-format="YYYY-MM-DD"
                          style="width: 100%" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="结算方式">
          <el-select v-model="extra.settle_type" filterable allow-create clearable
                     placeholder="可自定义" style="width: 100%">
            <el-option v-for="t in SETTLE_TYPES" :key="t" :label="t" :value="t" />
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
        <el-form-item label="收货仓库">
          <el-select v-model="extra.receipt_warehouse_id" filterable clearable
                     placeholder="默认收货仓库（可留空）" style="width: 100%" @visible-change="ensureOptions">
            <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="采购部门">
          <el-select v-model="extra.purchase_dept_id" filterable clearable
                     placeholder="选择部门（可留空）" style="width: 100%">
            <el-option v-for="o in orgs" :key="o.id" :label="o.name" :value="o.id" />
          </el-select>
        </el-form-item>
      </el-col>
    </template>
  </DocFormPage>

  <!-- V2.2：供货商详情（只读弹窗） -->
  <SupplierDetailDialog ref="supplierDialog" />
</template>
