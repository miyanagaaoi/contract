<script setup lang="ts">
/** 商品类型（T-V2-08 / AC-V2-09）：树形维护，仅叶子节点可挂物料。 */
import TreeMasterPage from '@/components/TreeMasterPage.vue'
import type { MasterField } from '@/types/master'

const fields: MasterField[] = [
  { prop: 'name', label: '类型名称', required: true, span: 24 },
  { prop: 'code', label: '类型编码', tip: '作为该类型下物料编码的前缀（如 RAW0001）' },
  { prop: 'sort', label: '排序', type: 'number', min: 0 },
  { prop: 'parent_id', label: '上级id', tip: '由界面自动带入，通常无需修改' },
]
</script>

<template>
  <TreeMasterPage title="商品类型" subtitle="物料的分类树；只有叶子类型可以挂物料"
                  api="/master/product-types" perm-view="master.ptype.view"
                  perm-edit="master.ptype.edit" node-label="类型" :fields="fields" />
</template>
