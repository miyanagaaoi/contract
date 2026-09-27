<script setup lang="ts">
/** 计量单位（T-V2-09 / AC-V2-11）：小数位决定数量录入与显示精度。 */
import MasterTablePage from '@/components/MasterTablePage.vue'
import type { MasterColumn, MasterField } from '@/types/master'

const columns: MasterColumn[] = [
  { prop: 'code', label: '编码', width: 110 },
  { prop: 'name', label: '单位名称', minWidth: 140 },
  { prop: 'decimals', label: '小数位', width: 90 },
  { prop: 'enabled', label: '状态', width: 80, kind: 'bool' },
  { prop: 'remark', label: '备注', minWidth: 160 },
]

const fields: MasterField[] = [
  { prop: 'code', label: '单位编码', required: true, placeholder: '如 PCS / KG / M' },
  { prop: 'name', label: '单位名称', required: true, placeholder: '如 个 / 千克 / 米' },
  { prop: 'decimals', label: '小数位', type: 'number', min: 0, max: 4, tip: '0~4 位' },
  { prop: 'enabled', label: '启用', type: 'switch' },
  { prop: 'remark', label: '备注', type: 'textarea', span: 24 },
]
</script>

<template>
  <MasterTablePage title="计量单位" subtitle="数量精度由单位小数位决定；已被物料引用时不能删除"
                   api="/master/uoms" perm-edit="master.uom.edit"
                   :columns="columns" :fields="fields" status-mode="bool" />
</template>
