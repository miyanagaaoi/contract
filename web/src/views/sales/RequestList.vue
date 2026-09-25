<script setup lang="ts">
/**
 * 销售申请单列表（T-V2-29，与采购申请单同构）。
 *
 * 通用列表能力（筛选 / 分页 / 权限动作 / 详情抽屉 / 导出 / 打印）由 `DocListPage` 提供，
 * 本页只补充销售申请特有字段与「下推销售订单」入口。
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import DocListPage from '@/components/doc/DocListPage.vue'
import PushDialog from '@/components/doc/PushDialog.vue'
import { fetchMasterOptions, type Dict } from '@/api'
import type { DocRecord } from '@/types/doc'

const router = useRouter()
const listRef = ref<InstanceType<typeof DocListPage> | null>(null)
const pushRef = ref<InstanceType<typeof PushDialog> | null>(null)

/** 行内「下推」→ 打开下推对话框（选客户 + 调整下推行/数量） */
function onPush(row: DocRecord) {
  pushRef.value?.open(row)
}

/** 下推成功：跳到销售订单编辑页继续完善（交期 / 收货信息等） */
function onPushed(doc: DocRecord) {
  listRef.value?.load()
  router.push({ name: 'sales-order-edit', params: { id: String(doc.id) } })
}

function fmtDate(v: unknown): string {
  return v ? String(v).slice(0, 10) : '—'
}

/** 部门 / 仓库显示名（详情抽屉里避免只显示 ID） */
const orgs = ref<Dict[]>([])

function deptName(id: unknown): string {
  if (!id) return '—'
  const hit = orgs.value.find((o) => o.id === Number(id))
  return hit ? hit.name : `ID ${id}`
}

onMounted(async () => {
  try {
    orgs.value = await fetchMasterOptions('org')
  } catch {
    orgs.value = []
  }
})
</script>

<template>
  <DocListPage ref="listRef" title="销售申请单" api="/api/sales/requests"
               subtitle="录入客户需求 → 提交 → 审核 → 下推销售订单；作废单据默认隐藏"
               perm-prefix="sales.request" kind-label="销售申请单"
               form-route="sales-request-form" edit-route="sales-request-edit"
               show-customer contract-source="sales"
               export-path="/api/sales/requests/export.xlsx"
               pushable push-perm="sales.order.create" :extra-cols="['ordered']"
               @push="onPush">
    <template #detail-head="{ detail }">
      <el-descriptions-item label="客户（文本）">{{ detail.customer_name_text || '—' }}</el-descriptions-item>
      <el-descriptions-item label="期望交期">{{ fmtDate(detail.expect_delivery_date) }}</el-descriptions-item>
      <el-descriptions-item label="销售部门" :span="2">
        {{ deptName(detail.sales_dept_id) }}
      </el-descriptions-item>
    </template>
  </DocListPage>

  <PushDialog ref="pushRef" api="/api/sales/requests" dest-type="order"
              dest-label="销售订单" party-kind="customer" @done="onPushed" />
</template>
