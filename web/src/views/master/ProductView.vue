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
  // V2.5+：编码由系统自动生成（留空即自动，按"商品类型码+序号"），**编辑时只读**——
  // 编码是审计线索（单据/库存/合同行项都存了快照），创建后改动会让历史单据对不上物料。
  // 显式传入仍按传入值（历史/导入场景），接口层保留该能力。
  { prop: 'code', label: '物料编码', placeholder: '留空自动生成（类型码+序号）', span: 24,
    readonlyOnEdit: true, tip: '留空即按商品类型码自动生成；保存后不再修改' },
  { prop: 'spec', label: '规格型号' },
  // V2.5+：品牌改为**从供应商档案选择**，显示并保存**简称**（无简称回落全称）：
  // 落库的仍是文本快照（`Product.brand`），供应商改名/停用不影响历史物料；
  // 旧数据的自由文本仍能显示（下拉里会带出历史值，不会被清空）。
  { prop: 'brand', label: '品牌', type: 'options', optionKind: 'supplier',
    storeText: true, textField: 'short_name', placeholder: '选择系统供应商（显示简称）',
    tip: '取供应商档案的简称（未维护简称时显示全称）；保存为简称快照' },
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
