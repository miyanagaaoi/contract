<script setup lang="ts">
/** 组织架构（T-V2-03）：树形维护，删除受校验约束（有子节点或归属账号时只能停用）。 */
import { onMounted, ref } from 'vue'

import TreeMasterPage from '@/components/TreeMasterPage.vue'
import { fetchMasterOptions } from '@/api'
import type { MasterField } from '@/types/master'

const fields: MasterField[] = [
  { prop: 'name', label: '节点名称', required: true, span: 24 },
  {
    prop: 'unit_type', label: '节点类型', type: 'select', required: true,
    options: ['公司', '部门', '岗位'].map((v) => ({ label: v, value: v })),
  },
  { prop: 'code', label: '节点编码' },
  { prop: 'phone', label: '联系电话' },
  {
    // 部门负责人：选系统账号（仅启用），可清空；直接存 user_id，显示名由后端即时 join 取
    prop: 'leader_user_id', label: '部门负责人', type: 'select',
    placeholder: '可空；用于打印时默认带出负责人姓名',
  },
  { prop: 'sort', label: '排序', type: 'number', min: 0 },
  { prop: 'parent_id', label: '上级id', tip: '由界面自动带入，通常无需修改' },
]

// 负责人候选为异步下拉，响应式传入（TreeMasterPage 渲染时优先取 fieldOptions）
const leaderOptions = ref<{ label: string; value: number }[]>([])
const fieldOptions = ref<Record<string, { label: string; value: number }[]>>({})

onMounted(async () => {
  try {
    const users = await fetchMasterOptions('user')
    leaderOptions.value = users.map((u) => ({ label: String(u.name), value: Number(u.id) }))
    fieldOptions.value = { leader_user_id: leaderOptions.value }
  } catch {
    // 下拉失败不阻塞树维护（此时该字段只是无候选，保存仍可清空/保持原值）
  }
})
</script>

<template>
  <TreeMasterPage title="组织架构" subtitle="最多 5 级；删除前必须无子节点且无归属账号"
                  api="/system/org-units" perm-edit="master.org.edit"
                  node-label="节点" :fields="fields" :field-options="fieldOptions" />
</template>
