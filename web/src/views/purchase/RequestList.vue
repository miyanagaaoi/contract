<script setup lang="ts">
/**
 * 采购申请单列表（T-V2-24，AC-V2-15~17）。
 *
 * 通用列表能力（筛选 / 分页 / 权限动作 / 详情抽屉）由 `DocListPage` 提供，
 * 本页只补充申请单特有字段与「下推采购单」入口。
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import DocListPage from '@/components/doc/DocListPage.vue'
import PushDialog from '@/components/doc/PushDialog.vue'
import { fetchMasterOptions, type Dict } from '@/api'
import type { DocRecord } from '@/types/doc'

const API = '/api/purchase/requests'
const router = useRouter()

const listRef = ref<InstanceType<typeof DocListPage> | null>(null)
const pushRef = ref<InstanceType<typeof PushDialog> | null>(null)

/** 行内「下推」→ 打开下推对话框（选供应商 + 调整下推行/数量） */
function onPush(row: DocRecord) {
  pushRef.value?.open(row)
}

/** 下推成功：跳到采购单编辑页继续完善（供应商/交期等） */
function onPushed(doc: DocRecord) {
  listRef.value?.load()
  router.push({ name: 'purchase-order-edit', params: { id: String(doc.id) } })
}

function fmtDate(v: unknown): string {
  return v ? String(v).slice(0, 10) : '—'
}

/** 建议供应商显示名（详情抽屉里避免只显示 ID） */
const suppliers = ref<Dict[]>([])

function supplierName(id: unknown): string {
  if (!id) return '—'
  const hit = suppliers.value.find((s) => s.id === Number(id))
  return hit ? hit.name : `ID ${id}`
}

onMounted(async () => {
  try {
    suppliers.value = await fetchMasterOptions('supplier')
  } catch {
    suppliers.value = []
  }
})
</script>

<template>
  <DocListPage ref="listRef" title="采购申请单" api="/api/purchase/requests"
               subtitle="录入需求 → 提交 → 审核 → 下推采购单；作废单据默认隐藏"
               perm-prefix="purchase.request" kind-label="采购申请单"
               form-route="purchase-request-form" edit-route="purchase-request-edit" show-supplier
               pushable push-perm="purchase.order.create"
               push-remain-field="remain_qty_sum"
               export-path="/api/purchase/requests/export.xlsx"
               :extra-cols="['ordered']" @push="onPush">
    <template #detail-head="{ detail }">
      <el-descriptions-item label="需求日期">{{ fmtDate(detail.need_date) }}</el-descriptions-item>
      <el-descriptions-item label="建议供应商">
        {{ supplierName(detail.suggest_supplier_id) }}
      </el-descriptions-item>
      <el-descriptions-item label="用途说明" :span="2">{{ detail.purpose || '—' }}</el-descriptions-item>
    </template>
  </DocListPage>

  <PushDialog ref="pushRef" api="/api/purchase/requests" dest-type="order"
              dest-label="采购单" @done="onPushed" />
</template>
