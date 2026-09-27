<script setup lang="ts">
/**
 * 采购申请单表单（T-V2-24）：表头 + 行项 + 保存草稿 / 保存并提交。
 *
 * 表头结构：单据日期、关联合同、经办人（通用）+ 需求日期、申请部门、建议供应商、用途说明（特有）。
 */
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import ContractDetailDrawer from '@/components/doc/ContractDetailDrawer.vue'
import DocFormPage from '@/components/doc/DocFormPage.vue'
import SupplierDetailDialog from '@/components/SupplierDetailDialog.vue'
import { fetchContract, fetchMasterOptions, type Dict } from '@/api'

const extra = ref<Dict>({
  request_dept_id: null,
  need_date: null,
  purpose: '',
  suggest_supplier_id: null,
})

const suppliers = ref<Dict[]>([])
const orgs = ref<Dict[]>([])

/** 建议供应商下拉（懒加载一次） */
async function ensureSuppliers() {
  if (suppliers.value.length) return
  try {
    suppliers.value = await fetchMasterOptions('supplier')
  } catch {
    suppliers.value = []
  }
}
void ensureSuppliers()

/** 组织（部门）下拉：来自 /api/master/options/org，登录即可取 */
async function ensureOrgs() {
  if (orgs.value.length) return
  try {
    orgs.value = await fetchMasterOptions('org')
  } catch {
    orgs.value = []
  }
}
void ensureOrgs()

const purpose = computed({
  get: () => (extra.value.purpose as string) ?? '',
  set: (v: string) => { extra.value = { ...extra.value, purpose: v } },
})
const needDate = computed({
  get: () => (extra.value.need_date as string | null) ?? null,
  set: (v: string | null) => { extra.value = { ...extra.value, need_date: v } },
})
const deptId = computed({
  get: () => (extra.value.request_dept_id as number | null) ?? null,
  set: (v: number | null) => { extra.value = { ...extra.value, request_dept_id: v } },
})
const suggestSupplierId = computed({
  get: () => (extra.value.suggest_supplier_id as number | null) ?? null,
  set: (v: number | null) => { extra.value = { ...extra.value, suggest_supplier_id: v } },
})

/**
 * V2.2：供货商**默认显示简称**（单据与口头沟通都用简称，全称太长）。
 * 下拉面板里把全称作为次要说明补在简称后面，避免两家供货商简称相近时选错。
 */
function supplierLabel(s: Dict): string {
  return (s.short_name as string) || (s.name as string) || ''
}

// ---------------- V2.2：供货商详情弹窗 ----------------
const supplierDialog = ref<InstanceType<typeof SupplierDetailDialog> | null>(null)

function openSupplier(id: number | null | undefined) {
  if (!id) return
  supplierDialog.value?.open(id)
}

// ---------------- V2.1 / N5：合同详情抽屉 ----------------
const drawer = ref<InstanceType<typeof ContractDetailDrawer> | null>(null)

// ---------------- V2.1 / N2：从关联合同提取行项 ----------------
const extracting = ref(false)

/**
 * 把关联合同的行项提取为本单明细（草稿值，可修改）。
 *
 * 约束（BR-V2.1-02/03）：
 * - 合同行项**必须已绑定物料**才能提取（未绑定的行无法带出物料，会被后端拒绝）；
 * - 单内已有行项时先二次确认，避免误覆盖已录入内容。
 */
async function extractFromContract(header: Dict, items: Record<string, any>[]) {
  const contractId = header?.contract_id
  if (!contractId) {
    ElMessage.warning('请先选择关联合同')
    return
  }
  extracting.value = true
  try {
    const contract = await fetchContract(Number(contractId))
    const rows = (contract.items || []) as Dict[]
    if (!rows.length) {
      ElMessage.warning('该合同没有行项，无法提取')
      return
    }
    const unbound = rows.filter((r) => !r.product_id).length
    if (unbound) {
      ElMessage.warning(`该合同有 ${unbound} 行未绑定物料，请先在合同台账补齐后再提取`)
      return
    }
    if (items.length) {
      try {
        await ElMessageBox.confirm(
          `当前已有 ${items.length} 行，提取将覆盖这些行项。是否继续？`,
          '确认覆盖', { type: 'warning', confirmButtonText: '覆盖', cancelButtonText: '取消' },
        )
      } catch {
        return
      }
    }
    items.splice(0, items.length)
    for (const r of rows) {
      items.push({
        product_id: r.product_id,
        product_code: r.product_code ?? '',
        product_name: r.product_name ?? '',
        spec: r.spec ?? null,
        qty: Number(r.qty) || 0,
        unit_price: Number(r.unit_price) || 0,
        warehouse_id: null,
        remark: r.remark ?? '',
      })
    }
    ElMessage.success(`已提取 ${rows.length} 行合同明细，可继续调整数量与单价`)
  } catch {
    // 拦截器已提示
  } finally {
    extracting.value = false
  }
}
</script>

<template>
  <DocFormPage v-model="extra" title="采购申请单" kind-label="采购申请单"
               api="/api/purchase/requests" perm-prefix="purchase.request"
               list-route="purchase-requests" show-warehouse :extra-cols="['ordered']">
    <template #header="{ header }">
      <el-col :span="12">
        <el-form-item label="需求日期">
          <el-date-picker v-model="needDate" type="date" value-format="YYYY-MM-DD"
                          placeholder="期望到货/使用日期" style="width: 100%" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="申请部门">
          <el-select v-model="deptId" filterable clearable placeholder="选择部门（可留空）"
                     style="width: 100%">
            <el-option v-for="o in orgs" :key="o.id" :label="o.name" :value="o.id" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="建议供应商">
          <!-- V2.2：下拉显示简称，右侧按钮点开只读供货商档案 -->
          <div class="field-with-action">
            <el-select v-model="suggestSupplierId" filterable clearable placeholder="仅作建议，可留空"
                       @visible-change="ensureSuppliers">
              <el-option v-for="s in suppliers" :key="s.id"
                         :label="supplierLabel(s)" :value="s.id">
                <span>{{ supplierLabel(s) }}</span>
                <span v-if="s.short_name && s.short_name !== s.name" class="opt-sub">{{ s.name }}</span>
              </el-option>
            </el-select>
            <el-button size="small" :disabled="!suggestSupplierId"
                       @click="openSupplier(suggestSupplierId)">供货商详情</el-button>
          </div>
        </el-form-item>
      </el-col>
      <el-col :span="24">
        <el-form-item label="用途说明">
          <el-input v-model="purpose" type="textarea" :rows="2" maxlength="200" show-word-limit
                    placeholder="本次采购的用途 / 背景" />
        </el-form-item>
      </el-col>
    </template>

    <!--
      V2.1 / N5：关联合同后可直接拉出只读合同详情，无需离开当前单据。
      按钮放在「关联合同」选择框右侧（DocFormPage 的 #contract-actions 插槽）并改为 small
      —— 原先它独占页底半行，与所服务的字段隔了好几个字段，视线要来回跳。
      注意：「请先选择关联合同」文案被 e2e 断言依赖（06-purchase.spec.ts:217），必须保留。
    -->
    <template #contract-actions="{ header }">
      <el-button size="small" :disabled="!header.contract_id"
                 @click="drawer?.open(header.contract_id)">查看合同详情</el-button>
      <span v-if="!header.contract_id" class="gray">请先选择关联合同</span>
    </template>

    <!-- V2.1 / N2：一键把关联合同的行项提取为本单明细（草稿值，可修改） -->
    <template #items-toolbar="{ header, items, editable }">
      <el-button v-if="editable" size="small" type="primary" plain
                 :disabled="!header.contract_id" :loading="extracting"
                 @click="extractFromContract(header, items)">
        提取合同明细
      </el-button>
    </template>
  </DocFormPage>

  <ContractDetailDrawer ref="drawer" />

  <!-- V2.2：供货商详情（只读弹窗） -->
  <SupplierDetailDialog ref="supplierDialog" />
</template>

<style scoped>
.gray { color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); }
</style>
