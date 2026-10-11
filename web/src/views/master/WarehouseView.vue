<script setup lang="ts">
/**
 * 仓库档案（T-V2-10）：库存与出入库单的归属。
 *
 * V2.3：新增「所属公司」—— 取值仅能来自系统设置的我方公司（主体码）；
 * 单据/库存/下拉统一以 `主体码-仓库名`（如 ZC-主仓）显示。
 */
import MasterTablePage from '@/components/MasterTablePage.vue'
import type { MasterColumn, MasterField } from '@/types/master'

const columns: MasterColumn[] = [
  { prop: 'code', label: '编码', width: 110 },
  { prop: 'name', label: '仓库名称', minWidth: 140 },
  { prop: 'subject_name', label: '所属公司', width: 130 },
  { prop: 'display_name', label: '显示名', minWidth: 130 },
  { prop: 'address', label: '地址', minWidth: 180 },
  { prop: 'keeper_name', label: '仓管员', width: 110 },
  { prop: 'enabled', label: '状态', width: 80, kind: 'bool' },
  { prop: 'remark', label: '备注', minWidth: 140 },
]

const fields: MasterField[] = [
  { prop: 'code', label: '仓库编码', required: true, placeholder: '如 WH01' },
  { prop: 'name', label: '仓库名称', required: true },
  { prop: 'subject_code', label: '所属公司', type: 'subjects', placeholder: '来自系统设置的我方公司' },
  { prop: 'address', label: '地址', span: 24 },
  { prop: 'enabled', label: '启用', type: 'switch' },
  { prop: 'remark', label: '备注', type: 'textarea', span: 24 },
]
</script>

<template>
  <MasterTablePage title="仓库" subtitle="多仓库库存；所属公司决定单据与库存中的默认显示名（ZC-主仓）"
                   api="/master/warehouses" perm-edit="master.wh.edit"
                   :columns="columns" :fields="fields" status-mode="bool" />
</template>
