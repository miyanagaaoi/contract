<script setup lang="ts">
/** 物料档案（T-V2-11 / AC-V2-10）：编码自动生成（类型码+序号）或手工、类型叶子校验、单位绑定、安全库存。 */
import MasterTablePage from '@/components/MasterTablePage.vue'
import type { ExtraFilter, MasterColumn, MasterField } from '@/types/master'

const columns: MasterColumn[] = [
  { prop: 'code', label: '物料编码', width: 140 },
  { prop: 'name', label: '物料名称', minWidth: 160 },
  { prop: 'spec', label: '规格型号', minWidth: 130 },
  { prop: 'product_type_name', label: '商品类型', width: 130 },
  { prop: 'uom_name', label: '单位', width: 80 },
  { prop: 'brand', label: '品牌', width: 100 },
  { prop: 'default_price', label: '默认单价', width: 110, kind: 'money' },
  { prop: 'safety_stock', label: '安全库存', width: 100 },
  { prop: 'status', label: '状态', width: 80, kind: 'status' },
]

const fields: MasterField[] = [
  { prop: 'name', label: '物料名称', required: true, span: 24 },
  {
    // V2.1（N14/N15）：商品类型改为**树状展开选择**（父节点禁用、只能选叶子），
    // 并在右侧提供「快速新增」——无需跳到商品类型页，避免丢失已填内容。
    prop: 'product_type_id', label: '商品类型', type: 'tree-select', quickCreate: 'product-type',
    required: true, span: 12, placeholder: '选择叶子类型',
  },
  // V2.1（N15）：计量单位同样支持现场快建
  { prop: 'uom_id', label: '计量单位', type: 'options', optionKind: 'uom',
    quickCreate: 'uom', required: true },
  { prop: 'code', label: '物料编码', placeholder: '留空自动生成（类型码+序号）', span: 24 },
  { prop: 'spec', label: '规格型号' },
  { prop: 'brand', label: '品牌' },
  { prop: 'barcode', label: '条码' },
  { prop: 'default_price', label: '默认单价', type: 'number', precision: 4, min: 0 },
  { prop: 'safety_stock', label: '安全库存', type: 'number', precision: 3, min: 0 },
  { prop: 'remark', label: '备注', type: 'textarea', span: 24 },
]

const extraFilters: ExtraFilter[] = [
  { prop: 'product_type_id', label: '商品类型', optionKind: 'product-type' },
]
</script>

<template>
  <MasterTablePage title="物料档案" subtitle="物料只能挂在商品类型的叶子节点；编码留空时按类型码自动生成"
                   api="/master/products"
                   perm-edit="master.product.edit" :columns="columns" :fields="fields"
                   :extra-filters="extraFilters"
                   keyword-placeholder="名称 / 编码 / 规格 / 品牌 / 条码" />
</template>
