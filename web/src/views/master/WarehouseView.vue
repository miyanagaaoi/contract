<script setup lang="ts">
/** 仓库档案（T-V2-10）：库存与出入库单的归属。 */
import MasterTablePage from '@/components/MasterTablePage.vue'
import type { MasterColumn, MasterField } from '@/types/master'

const columns: MasterColumn[] = [
  { prop: 'code', label: '编码', width: 110 },
  { prop: 'name', label: '仓库名称', minWidth: 140 },
  { prop: 'address', label: '地址', minWidth: 180 },
  { prop: 'keeper_name', label: '仓管员', width: 110 },
  { prop: 'enabled', label: '状态', width: 80, kind: 'bool' },
  { prop: 'remark', label: '备注', minWidth: 140 },
]

const fields: MasterField[] = [
  { prop: 'code', label: '仓库编码', required: true, placeholder: '如 WH01' },
  { prop: 'name', label: '仓库名称', required: true },
  { prop: 'address', label: '地址', span: 24 },
  { prop: 'enabled', label: '启用', type: 'switch' },
  { prop: 'remark', label: '备注', type: 'textarea', span: 24 },
]
</script>

<template>
  <MasterTablePage title="仓库" subtitle="多仓库库存；已有库存或单据记录时不能删除"
                   api="/master/warehouses" perm-view="master.wh.view" perm-edit="master.wh.edit"
                   :columns="columns" :fields="fields" status-mode="bool" />
</template>
