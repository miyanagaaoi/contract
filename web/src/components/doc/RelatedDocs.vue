<script setup lang="ts">
/**
 * 合同关联单据（V2.0，采购线）：只读区块。
 *
 * 数据来源 `GET /api/contracts/{id}/related-docs`。该接口可能尚未就绪
 * （404 / 500），此时按需求**容错展示「—」**，并在控制台静默忽略，不打扰用户。
 */
import { ref } from 'vue'

import { fetchContractRelatedDocs } from '@/api'
import DocStatusTag from '@/components/doc/DocStatusTag.vue'
import type { ContractRelatedResult } from '@/types/doc'

const props = defineProps<{ contractId: number }>()

const loading = ref(false)
const data = ref<ContractRelatedResult | null>(null)
/** 接口不可用标记（404/异常），UI 显示「—」 */
const unavailable = ref(false)

function fmtMoney(v: unknown): string {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  return Number.isNaN(n) ? String(v) : n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtDate(v: unknown): string {
  return v ? String(v).slice(0, 10) : '—'
}

/** 汇总字段中文名 */
const SUMMARY_LABELS: Record<string, string> = {
  purchase_order_count: '采购单数',
  purchase_order_amount: '已下单金额',
  stock_in_count: '入库单数',
  stock_in_amount: '入库金额',
  sales_order_count: '销售订单数',
  sales_order_amount: '已接单金额',
  stock_out_count: '出库单数',
  stock_out_amount: '出库金额',
}

function summaryText(): string {
  const summary = data.value?.summary
  if (!summary) return '—'
  const parts = Object.entries(summary)
    .filter(([, v]) => v !== null && v !== undefined)
    .map(([k, v]) => {
      const label = SUMMARY_LABELS[k] ?? k
      const isMoney = k.endsWith('amount')
      return `${label} ${isMoney ? fmtMoney(v) : v}`
    })
  return parts.length ? parts.join(' · ') : '—'
}

async function load() {
  if (!props.contractId) return
  loading.value = true
  unavailable.value = false
  try {
    data.value = await fetchContractRelatedDocs(props.contractId)
  } catch {
    // 接口未就绪（404）或异常：静默容错，界面显示「—」
    data.value = null
    unavailable.value = true
  } finally {
    loading.value = false
  }
}

defineExpose({ load })
</script>

<template>
  <div v-loading="loading">
    <el-divider content-position="left">关联单据（采购线）</el-divider>

    <div class="summary">
      已下单金额汇总：<b>{{ summaryText() }}</b>
      <span v-if="unavailable" class="gray">（关联单据接口暂不可用，显示「—」）</span>
    </div>

    <el-table v-if="data?.docs?.length" :data="data.docs" size="small" border class="mt">
      <el-table-column prop="kind_label" label="单据类型" width="110" />
      <el-table-column prop="doc_no" label="单号" width="160" show-overflow-tooltip />
      <el-table-column label="日期" width="100">
        <template #default="{ row }">{{ fmtDate(row.doc_date) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="94">
        <template #default="{ row }">
          <DocStatusTag :status="row.status" :label="row.status_label" />
        </template>
      </el-table-column>
      <el-table-column label="金额" width="110" align="right">
        <template #default="{ row }">{{ fmtMoney(row.total_amount) }}</template>
      </el-table-column>
    </el-table>
    <el-empty v-else-if="!loading" :description="unavailable ? '关联单据：—' : '暂无关联单据'" :image-size="60" />
  </div>
</template>

<style scoped>
.summary { font-size: 13px; color: #606266; }
.summary b { color: #f56c6c; }
.gray { color: #909399; font-size: 12.5px; margin-left: 6px; }
.mt { margin-top: 8px; }
</style>
