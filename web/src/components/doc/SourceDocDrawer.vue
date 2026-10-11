<script setup lang="ts">
/**
 * 来源单据抽屉：在任意单据列表/详情里点「来源单号」即可看上游单据，不用再跳到对应列表翻。
 *
 * 为什么做成通用组件：来源关系是**全系统**的（入库单来自采购单、付款单来自采购单、
 * 发票来自采购/销售订单…），把"点开来源"只做在付款单上，其它列表马上就会提同样的需求。
 *
 * 数据范围与权限**由后端把关**（`GET {api}/{id}` 走 `apply_data_scope` + 查看权限）：
 * 看不到的上游单据只会返回 403/404，这里降级成一句可读提示，不抛异常。
 */
import { computed, ref, watch } from 'vue'

import { fetchDoc, type Dict } from '@/api'
import { fmtDate, fmtMoney } from '@/utils/format'

const props = defineProps<{
  modelValue: boolean
  docType?: string | null
  docId?: number | null
}>()

const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

/** 单据类型 → 接口前缀（与 `web/src/router/index.ts` 的列表路由同源） */
const API_OF: Record<string, string> = {
  purchase_request: '/api/purchase/requests',
  purchase_order: '/api/purchase/orders',
  sales_request: '/api/sales/requests',
  sales_order: '/api/sales/orders',
  stock_in: '/api/stock/in-orders',
  stock_out: '/api/stock/out-orders',
  stock_take: '/api/stock/takes',
  stock_transfer: '/api/stock/transfers',
  payment: '/api/finance/payments',
  receipt: '/api/finance/receipts',
  invoice: '/api/finance/invoices',
}

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const loading = ref(false)
const failed = ref(false)
const detail = ref<Dict | null>(null)

async function load() {
  detail.value = null
  failed.value = false
  const api = API_OF[String(props.docType || '')]
  if (!props.modelValue || !api || !props.docId) {
    failed.value = !!props.modelValue
    return
  }
  loading.value = true
  try {
    detail.value = await fetchDoc(api, Number(props.docId))
  } catch {
    failed.value = true          // 已删除 / 超出数据范围 / 无查看权限
  } finally {
    loading.value = false
  }
}

watch(() => [props.modelValue, props.docType, props.docId], () => { void load() }, { immediate: true })

/** 往来单位（采购方向看供应商、销售方向看客户，发票看票面对手方） */
const party = computed(() => {
  const doc = detail.value || {}
  return (doc.supplier_name || doc.customer_name || doc.party_name
    || doc.customer_name_text || '—') as string
})

const items = computed<Dict[]>(() => (detail.value?.items as Dict[]) || [])
</script>

<template>
  <el-drawer v-model="visible" size="min(760px, 94vw)"
             :title="`来源单据${detail?.doc_no ? ' ' + detail.doc_no : ''}`">
    <div v-loading="loading">
      <el-alert v-if="failed" type="warning" :closable="false" show-icon
                title="无法打开该来源单据"
                description="可能已被删除、超出你的数据范围，或当前账号没有该模块的查看权限。" />
      <template v-else-if="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="单据编号">{{ detail.doc_no }}</el-descriptions-item>
          <el-descriptions-item label="单据类型">
            {{ detail.kind_label || detail.doc_type }}
          </el-descriptions-item>
          <el-descriptions-item label="单据日期">{{ fmtDate(detail.doc_date) }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag size="small" effect="light">{{ detail.status_label || detail.status }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="签约公司">
            {{ detail.subject_name || detail.subject_code || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="往来单位">{{ party }}</el-descriptions-item>
          <el-descriptions-item label="金额">{{ fmtMoney(detail.total_amount) }}</el-descriptions-item>
          <el-descriptions-item label="经办人">{{ detail.handler_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="关联合同">{{ detail.contract_no || '—' }}</el-descriptions-item>
          <el-descriptions-item label="来源单据">{{ detail.source_doc_no || '—' }}</el-descriptions-item>
          <el-descriptions-item label="备注" :span="2">{{ detail.remark || '—' }}</el-descriptions-item>
        </el-descriptions>

        <el-table v-if="items.length" :data="items" size="small" border class="mt">
          <el-table-column prop="seq" label="#" width="52" />
          <el-table-column prop="product_name" label="物料" min-width="140" />
          <el-table-column prop="spec" label="规格" min-width="110" />
          <el-table-column prop="uom_name" label="单位" width="70" />
          <el-table-column prop="qty" label="数量" width="90" align="right" />
          <el-table-column label="单价" width="100" align="right">
            <template #default="{ row }">{{ fmtMoney(row.unit_price) }}</template>
          </el-table-column>
          <el-table-column label="金额" width="110" align="right">
            <template #default="{ row }">{{ fmtMoney(row.amount) }}</template>
          </el-table-column>
        </el-table>

        <!-- 财务上游（如付款单来自发票核销）：核销明细也一并展示，避免"只看得到金额" -->
        <el-table v-if="detail.allocations?.length" :data="detail.allocations" size="small"
                  border class="mt">
          <el-table-column prop="target_label" label="核销目标" width="110" />
          <el-table-column prop="target_no" label="目标单号" min-width="140" />
          <el-table-column label="金额" width="120" align="right">
            <template #default="{ row }">{{ fmtMoney(row.amount) }}</template>
          </el-table-column>
          <el-table-column prop="remark" label="备注" min-width="120" />
        </el-table>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
.mt { margin-top: var(--ctms-gap); }
</style>
