<script setup lang="ts">
/**
 * 供货商详情弹窗（V2.2）。
 *
 * 用途：采购申请单 / 采购单等页面里，凡是出现供货商的地方都可点击，
 * 点击后**不离开当前页面**弹出该供货商的完整档案（简称、编码、联系人、账期、
 * 供货范围等），避免"为了核对一个电话/账期而跳去资料库、回来发现单据没保存"。
 *
 * 口径：
 * - 弹窗标题与首行**默认显示简称**（单据与口头沟通都用简称，全称太长）；
 *   没有简称的存量档案回退显示全称，不会出现空白标题；
 * - 只读，不修改任何数据；调用方通过 `ref` 调 `open(supplierId)` 打开。
 */
import { computed, ref } from 'vue'

import { fetchMasterItem, type Dict } from '@/api'

const visible = ref(false)
const loading = ref(false)
const supplier = ref<Dict | null>(null)
const failed = ref(false)
const failedStatus = ref<number | null>(null)

/** 简称优先的展示名（无简称回退全称，再回退编码） */
const displayName = computed(() => {
  const s = supplier.value
  if (!s) return ''
  return (s.short_name as string) || (s.name as string) || (s.code as string) || ''
})

const fullName = computed(() => (supplier.value?.name as string) || '—')

/** 打开并加载指定供货商档案（`id` 为空时不动作） */
async function open(id: number | null | undefined): Promise<void> {
  if (!id) return
  visible.value = true
  loading.value = true
  supplier.value = null
  failed.value = false
  failedStatus.value = null
  try {
    supplier.value = await fetchMasterItem('/master/suppliers', Number(id))
  } catch (error) {
    // 与合同抽屉一致：失败要有明确落点，不能只靠一闪而过的 toast
    failed.value = true
    failedStatus.value = (error as { response?: { status?: number } })?.response?.status ?? null
  } finally {
    loading.value = false
  }
}

defineExpose({ open })
</script>

<template>
  <el-dialog v-model="visible" :title="displayName ? `供货商详情 · ${displayName}` : '供货商详情'"
             width="min(680px, 92vw)">
    <div v-loading="loading">
      <el-alert v-if="failed && !loading" type="error" :closable="false" show-icon class="mb"
                :title="failedStatus === 403 ? '没有查看供货商档案的权限' : '供货商详情加载失败'"
                :description="failedStatus === 403
                  ? '当前账号缺少「供应商查看」（master.supplier.view）权限，请联系管理员开通。'
                  : '请关闭后重试；若持续失败请检查网络或联系管理员。'" />

      <template v-if="supplier">
        <!-- 默认突出显示简称：这是业务上真正用来指代这家供货商的字段 -->
        <div class="name-bar">
          <span class="short">{{ displayName || '—' }}</span>
          <span v-if="supplier.short_name && supplier.name" class="full">{{ supplier.name }}</span>
          <el-tag v-if="supplier.status" class="ml" size="small"
                  :type="supplier.status === 'enabled' ? 'success' : 'info'">
            {{ supplier.status === 'enabled' ? '启用' : '停用' }}
          </el-tag>
        </div>

        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="简称">
            <b>{{ supplier.short_name || '—' }}</b>
          </el-descriptions-item>
          <el-descriptions-item label="供货商编码">{{ supplier.code || '—' }}</el-descriptions-item>
          <el-descriptions-item label="供货商全称" :span="2">{{ fullName }}</el-descriptions-item>
          <el-descriptions-item label="等级">{{ supplier.level || '—' }}</el-descriptions-item>
          <el-descriptions-item label="账期(天)">
            {{ supplier.payment_days === null || supplier.payment_days === undefined
              ? '—' : `${supplier.payment_days} 天` }}
          </el-descriptions-item>
          <el-descriptions-item label="联系人">{{ supplier.contact_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="联系电话">{{ supplier.contact_phone || '—' }}</el-descriptions-item>
          <el-descriptions-item label="税号" :span="2">{{ supplier.tax_no || '—' }}</el-descriptions-item>
          <el-descriptions-item label="开户行">{{ supplier.bank_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="银行账号">{{ supplier.bank_account || '—' }}</el-descriptions-item>
          <el-descriptions-item label="供货范围" :span="2">{{ supplier.supply_scope || '—' }}</el-descriptions-item>
          <el-descriptions-item label="地址" :span="2">{{ supplier.address || '—' }}</el-descriptions-item>
          <el-descriptions-item label="备注" :span="2">{{ supplier.remark || '—' }}</el-descriptions-item>
        </el-descriptions>
      </template>
    </div>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.mb { margin-bottom: var(--ctms-gap); }
.ml { margin-left: var(--ctms-gap-sm); }
.name-bar {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--ctms-gap-sm);
  margin-bottom: var(--ctms-gap);
  padding-bottom: var(--ctms-gap-sm);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.short { font-size: var(--ctms-fs-md); font-weight: 600; }
.full { color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); }
</style>
