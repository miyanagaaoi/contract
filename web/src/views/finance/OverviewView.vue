<script setup lang="ts">
/**
 * 资金概览（M3 起步，`GET /api/finance/summary`）。
 *
 * 目的：把已经算准的进度口径变成管理层一眼能看的四个数 —— **待付 / 待收 / 待收票 / 待开票**，
 * 以及"发票待认证""超额核销"两个提醒。口径与采购单/销售订单列表的进度列**同源**
 * （都取 `paid_amount` / `invoiced_amount` 等回写字段），因此不会出现"看板说还欠 3 万、
 * 列表说未付 3 万"这类口径漂移。
 *
 * 每张卡片下方列出金额最大的若干张单据，可直接点进详情安排付款/开票。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { fetchFinanceSummary, type Dict } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { fmtDate, fmtMoney } from '@/utils/format'

const auth = useAuthStore()
const router = useRouter()
const data = ref<Dict | null>(null)
const loading = ref(false)

const canRecalc = computed(() => auth.hasPerm('finance.payment.approve'))

async function load() {
  loading.value = true
  try {
    data.value = await fetchFinanceSummary()
  } catch {
    data.value = null      // 无权限/接口异常：页面显示空态，不影响其它功能
  } finally {
    loading.value = false
  }
}

function openDoc(row: Dict) {
  router.push({ name: 'finance-payment-detail', params: { id: String(row.id) } })
}

onMounted(load)
</script>

<template>
  <el-card v-loading="loading" shadow="never">
    <template #header>
      <div class="head">
        <div>
          <span class="title">资金概览</span>
          <span class="subtitle">
            只统计已审核/已完成且未作废的单据；口径与采购单/销售订单的进度列同源
          </span>
        </div>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </template>

    <el-empty v-if="!data" description="暂无可展示的资金数据（或当前账号无财务查看权限）" />

    <template v-else>
      <el-row :gutter="12">
        <el-col :span="6">
          <div class="stat">
            <div class="label">采购待付</div>
            <div class="value">{{ fmtMoney(data.purchase?.open_payment?.amount || 0) }}</div>
            <div class="tip">{{ data.purchase?.open_payment?.count || 0 }} 张采购单</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat">
            <div class="label">采购待收票</div>
            <div class="value">{{ fmtMoney(data.purchase?.open_invoice?.amount || 0) }}</div>
            <div class="tip">{{ data.purchase?.open_invoice?.count || 0 }} 张采购单</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat">
            <div class="label">销售待收</div>
            <div class="value green">{{ fmtMoney(data.sales?.open_receipt?.amount || 0) }}</div>
            <div class="tip">{{ data.sales?.open_receipt?.count || 0 }} 张销售订单</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat">
            <div class="label">销售待开票</div>
            <div class="value green">{{ fmtMoney(data.sales?.open_invoice?.amount || 0) }}</div>
            <div class="tip">{{ data.sales?.open_invoice?.count || 0 }} 张销售订单</div>
          </div>
        </el-col>
      </el-row>

      <div class="alerts">
        <el-tag v-if="data.invoice?.pending_auth_count" type="warning" size="small">
          待认证发票 {{ data.invoice.pending_auth_count }} 张 ·
          {{ fmtMoney(data.invoice.pending_auth_amount) }}
        </el-tag>
        <el-tag v-if="data.over?.payment" type="danger" size="small">
          超额付款 {{ data.over.payment }} 张
        </el-tag>
        <el-tag v-if="data.over?.receipt" type="danger" size="small">
          超额收款 {{ data.over.receipt }} 张
        </el-tag>
        <el-tag v-if="data.over?.invoice" type="danger" size="small">
          超额开票 {{ data.over.invoice }} 张
        </el-tag>
        <span v-if="canRecalc" class="tip">
          对不上时可在「付款单/收款单」列表点「重算回写」按核销明细校正。
        </span>
      </div>

      <el-row :gutter="12">
        <el-col :span="12">
          <div class="block-title">金额最大的待付款采购单</div>
          <el-table :data="data.purchase?.open_payment?.top || []" size="small" border>
            <el-table-column prop="doc_no" label="单号" width="160" />
            <el-table-column prop="party" label="供应商" min-width="120" />
            <el-table-column label="日期" width="105">
              <template #default="{ row }">{{ fmtDate(row.doc_date) }}</template>
            </el-table-column>
            <el-table-column label="未付" width="110" align="right">
              <template #default="{ row }"><b>{{ fmtMoney(row.open_amount) }}</b></template>
            </el-table-column>
            <template #empty>没有待付款的采购单</template>
          </el-table>
        </el-col>
        <el-col :span="12">
          <div class="block-title">金额最大的待收款销售订单</div>
          <el-table :data="data.sales?.open_receipt?.top || []" size="small" border>
            <el-table-column prop="doc_no" label="单号" width="160" />
            <el-table-column prop="party" label="客户" min-width="120" />
            <el-table-column label="日期" width="105">
              <template #default="{ row }">{{ fmtDate(row.doc_date) }}</template>
            </el-table-column>
            <el-table-column label="未收" width="110" align="right">
              <template #default="{ row }"><b>{{ fmtMoney(row.open_amount) }}</b></template>
            </el-table-column>
            <template #empty>没有待收款的销售订单</template>
          </el-table>
        </el-col>
      </el-row>
    </template>
  </el-card>
</template>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; }
.title { font-weight: 600; font-size: var(--ctms-fs-md); }
.subtitle { margin-left: 10px; color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); }
.stat {
  border: 1px solid var(--ctms-border, #e5e7eb);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: var(--ctms-gap);
}
.stat .label { color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); }
.stat .value { font-size: 22px; font-weight: 700; margin: 6px 0 2px; }
.stat .value.green { color: #1f9d55; }
.stat .tip { color: var(--ctms-text-muted); font-size: var(--ctms-fs-xs); }
.alerts { display: flex; align-items: center; gap: 10px; margin: 4px 0 var(--ctms-gap); flex-wrap: wrap; }
.block-title { font-weight: 600; margin-bottom: 6px; }
.tip { color: var(--ctms-text-muted); font-size: var(--ctms-fs-xs); }
</style>
