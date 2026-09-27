<script setup lang="ts">
/** 组织架构（T-V2-03）：树形维护，删除受校验约束（有子节点或归属账号时只能停用）。 */
import TreeMasterPage from '@/components/TreeMasterPage.vue'
import type { MasterField } from '@/types/master'

const fields: MasterField[] = [
  { prop: 'name', label: '节点名称', required: true, span: 24 },
  {
    prop: 'unit_type', label: '节点类型', type: 'select', required: true,
    options: ['公司', '部门', '岗位'].map((v) => ({ label: v, value: v })),
  },
  { prop: 'code', label: '节点编码' },
  { prop: 'phone', label: '联系电话' },
  { prop: 'sort', label: '排序', type: 'number', min: 0 },
  { prop: 'parent_id', label: '上级id', tip: '由界面自动带入，通常无需修改' },
]
</script>

<template>
  <TreeMasterPage title="组织架构" subtitle="最多 5 级；删除前必须无子节点且无归属账号"
                  api="/system/org-units" perm-edit="master.org.edit"
                  node-label="节点" :fields="fields" />
</template>
