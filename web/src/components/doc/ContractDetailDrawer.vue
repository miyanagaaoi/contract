<script setup lang="ts">
/**
 * 合同详情抽屉（V2.1 / N5，只读）。
 *
 * 用途：单据页（如采购申请单）选了"关联合同"后，点按钮即可在**不离开当前表单**的前提下
 * 核对合同金额、行项与关联单据——避免"为了看一眼合同而丢失未保存的单据"。
 *
 * 只读、不修改任何数据；关闭后单据页的录入状态不受影响。
 */
import { ref } from 'vue'

import { fetchContract, fetchContractRelatedDocs, type Dict } from '@/api'

const visible = ref(false)
const loading = ref(false)
const contract = ref<Dict | null>(null)
const related = ref<Dict[]>([])

function fmtMoney(v: unknown): string {
  if (v === null || v === undefined || v === '') return '0.00'
  const n = Number(v)
  if (!Number.isFinite(n)) return '0.00'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** 打开抽屉并加载指定合同（`id` 为空时不动作） */
async function open(id: number | null | undefined) {
  if (!id) return
  visible.value = true
  loading.value = true
  contract.value = null
  related.value = []
  try {
    contract.value = await fetchContract(id)
  } catch {
    // 拦截器已提示
  }
  try {
    const res: Dict = await fetchContractRelatedDocs(id)
    related.value = (res?.items ?? res?.docs ?? []) as Dict[]
  } catch {
    related.value = []
  } finally {
    loading.value = false
  }
}

defineExpose({ open })
</script>

<template>
  <el-drawer v-model="visible" title="合同详情（只读）" size="46%" :destroy-on-close="false">
    <div v-loading="loading">
      <template v-if="contract">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="合同编号">{{ contract.contract_no || '—' }}</el-descriptions-item>
          <el-descriptions-item label="合同状态">{{ contract.status || '—' }}</el-descriptions-item>
          <el-descriptions-item label="合同名称" :span="2">{{ contract.name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="甲方">{{ contract.party_a || '—' }}</el-descriptions-item>
          <el-descriptions-item label="乙方">{{ contract.party_b || '—' }}</el-descriptions-item>
          <el-descriptions-item label="签订日期">{{ contract.sign_date || '—' }}</el-descriptions-item>
          <el-descriptions-item label="合同金额">{{ fmtMoney(contract.amount) }}</el-descriptions-item>
          <el-descriptions-item label="累计已付">{{ fmtMoney(contract.paid_amount) }}</el-descriptions-item>
          <el-descriptions-item label="经办人">{{ contract.owner_name || '—' }}</el-descriptions-item>
        </el-descriptions>

        <el-divider content-position="left">行项明细（{{ (contract.items || []).length }} 行）</el-divider>
        <el-table :data="contract.items || []" border size="small" max-height="240">
          <el-table-column type="index" label="#" width="46" />
          <el-table-column label="物料" min-width="160">
            <template #default="{ row }">
              {{ row.product_name || row.name || '—' }}
              <span v-if="row.product_code" class="gray">（{{ row.product_code }}）</span>
            </template>
          </el-table-column>
          <el-table-column prop="spec" label="规格型号" min-width="110" />
          <el-table-column label="数量" width="90" align="right">
            <template #default="{ row }">{{ row.qty ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="单价" width="100" align="right">
            <template #default="{ row }">{{ fmtMoney(row.unit_price) }}</template>
          </el-table-column>
          <el-table-column label="总价" width="110" align="right">
            <template #default="{ row }">{{ fmtMoney(row.total) }}</template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!(contract.items || []).length" description="该合同暂无行项" :image-size="60" />

        <el-divider content-position="left">关联单据（只读汇总）</el-divider>
        <el-table v-if="related.length" :data="related" border size="small" max-height="200">
          <el-table-column prop="doc_no" label="单号" min-width="150" />
          <el-table-column prop="kind_label" label="类型" width="110" />
          <el-table-column prop="status_label" label="状态" width="90" />
          <el-table-column label="金额" width="110" align="right">
            <template #default="{ row }">{{ fmtMoney(row.total_amount) }}</template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无关联单据" :image-size="60" />
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
.gray { color: #909399; font-size: 12px; }
</style>
