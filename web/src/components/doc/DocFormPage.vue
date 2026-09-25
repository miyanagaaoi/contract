<script setup lang="ts">
/**
 * 通用单据表单壳（V2.0，T-V2-24）。
 *
 * 结构：表头（两列）+ 行项表格 + 底部「保存草稿 / 保存并提交 / 返回」。
 * 各单据的特有表头字段由页面通过 `#header` 插槽补充；表头扩展字段双向绑定到
 * `modelValue`（父页面用 `v-model="headerExtra"` 传入），保存时与通用字段合并提交。
 *
 * 注意：仅草稿可编辑（后端 `assert_editable` 同样校验）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import DocItemsTable from '@/components/doc/DocItemsTable.vue'
import DocStatusTag from '@/components/doc/DocStatusTag.vue'
import {
  createDoc,
  docAction,
  fetchDoc,
  fetchPurchaseContractOptions,
  fetchSalesContractOptions,
  openDocPrint,
  updateDoc,
  type Dict,
} from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { DocRecord } from '@/types/doc'

type ExtraCol = 'ordered' | 'received' | 'shipped' | 'book' | 'actual' | 'diff'

const props = withDefaults(defineProps<{
  title: string
  /** 接口前缀，如 '/api/purchase/requests' */
  api: string
  /** 权限点前缀 */
  permPrefix: string
  /** 列表路由名（返回与保存后跳转） */
  listRoute: string
  /** 单据类型标签 */
  kindLabel: string
  /** 行项是否可编辑（入库单下推时数量可改、单价只读） */
  itemsEditable?: boolean
  /** 是否允许编辑行单价 */
  showPrice?: boolean
  showWarehouse?: boolean
  extraCols?: ExtraCol[]
  /** 表头扩展字段（由父页面 v-model 传入，保存时合并） */
  modelValue?: Dict
  /** 是否强制要求至少一行行项（盘点单先建单再生成行项，需置 false） */
  requireItems?: boolean
  /** 保存时是否提交行项（盘点单行项由「生成行项 / 录入实盘」维护，需置 false） */
  submitItems?: boolean
  /** 保存后是否跳回列表（盘点单需留在详情页继续生成行项） */
  redirectAfterSave?: boolean
  /** 表头必填校验（后端同样强制，这里只做友好提示） */
  extraRequired?: { key: string; label: string }[]
  /** 是否显示「打印」按钮（单据已保存后可用） */
  printable?: boolean
  /** 打印接口前缀（缺省与 api 相同） */
  printApi?: string
  /** 关联合同下拉数据源：采购方向 / 销售方向 */
  contractSource?: 'purchase' | 'sales'
}>(), {
  itemsEditable: true,
  showPrice: true,
  showWarehouse: false,
  extraCols: () => [],
  modelValue: () => ({}),
  requireItems: true,
  submitItems: true,
  redirectAfterSave: true,
  extraRequired: () => [],
  printable: true,
  printApi: '',
  contractSource: 'purchase',
})

const emit = defineEmits<{
  'update:modelValue': [value: Dict]
  /** 保存成功（父页面可据 doc.id 决定后续跳转，如盘点单转编辑态） */
  saved: [doc: DocRecord]
}>()

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const docId = computed(() => {
  const raw = route.params.id
  return raw ? Number(raw) : null
})
const isEdit = computed(() => !!docId.value)

const loading = ref(false)
const saving = ref(false)
const detail = ref<DocRecord | null>(null)
const items = ref<Record<string, any>[]>([])
const contracts = ref<Dict[]>([])

const header = reactive<{
  doc_date: string
  handler_user_id: number | null
  contract_id: number | null
  remark: string
}>({
  doc_date: new Date().toISOString().slice(0, 10),
  handler_user_id: auth.user?.id ?? null,
  contract_id: null,
  remark: '',
})

/** 表头扩展字段（特有字段）：父页面用 v-model 绑定 */
const extra = computed<Dict>({
  get: () => props.modelValue ?? {},
  set: (v: Dict) => emit('update:modelValue', v),
})

function setExtra(key: string, value: unknown) {
  extra.value = { ...(props.modelValue ?? {}), [key]: value }
}

/** 供父页面插槽直接调用：修改某个扩展字段 */
function patchExtra(key: string, value: unknown) {
  setExtra(key, value)
}

const canSave = computed(() => auth.hasPerm(`${props.permPrefix}.edit`))
const canSubmit = computed(() => auth.hasPerm(`${props.permPrefix}.submit`))

/** 仅草稿可编辑（新建时视为可编辑） */
const editable = computed(() => !isEdit.value || !!detail.value?.editable)

async function load() {
  if (!docId.value) return
  loading.value = true
  try {
    const doc = await fetchDoc(props.api, docId.value)
    detail.value = doc
    header.doc_date = doc.doc_date || header.doc_date
    header.handler_user_id = doc.handler_user_id ?? null
    header.contract_id = doc.contract_id ?? null
    header.remark = doc.remark ?? ''
    items.value = (doc.items || []).map((it) => ({ ...it }))
    // 把特有字段回填到父页面
    const next: Dict = { ...(props.modelValue ?? {}) }
    for (const key of Object.keys(next)) next[key] = (doc as Dict)[key] ?? null
    emit('update:modelValue', next)
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function validateItems(): boolean {
  if (!items.value.length) {
    ElMessage.warning('请至少添加一行行项')
    return false
  }
  for (let i = 0; i < items.value.length; i += 1) {
    const row = items.value[i]
    if (!row.product_id) {
      ElMessage.warning(`第 ${i + 1} 行：请选择物料`)
      return false
    }
    if (!(Number(row.qty) > 0)) {
      ElMessage.warning(`第 ${i + 1} 行：数量必须大于 0`)
      return false
    }
    const decimals = row.uom_decimals === null || row.uom_decimals === undefined ? 2 : Number(row.uom_decimals)
    const qtyText = String(Number(row.qty))
    const dot = qtyText.indexOf('.')
    if (decimals === 0 && (dot >= 0 ? Number(qtyText.slice(dot + 1)) > 0 : false)) {
      ElMessage.warning(`第 ${i + 1} 行：单位不支持小数，数量请填整数`)
      return false
    }
    if (dot >= 0 && qtyText.length - dot - 1 > decimals) {
      ElMessage.warning(`第 ${i + 1} 行：数量小数位超过单位允许的 ${decimals} 位`)
      return false
    }
  }
  return true
}

function validate(): boolean {
  if (!header.doc_date) {
    ElMessage.warning('请选择单据日期')
    return false
  }
  if (props.requireItems && !validateItems()) return false
  return true
}

function buildPayload(): Dict {
  const payload: Dict = {
    doc_date: header.doc_date,
    remark: header.remark || null,
    contract_id: header.contract_id || null,
    handler_user_id: header.handler_user_id || null,
  }
  // 盘点单的行项由「生成行项 / 录入实盘」维护，保存表头时不能整表覆盖（submitItems=false）
  if (props.submitItems) {
    payload.items = items.value.map((row) => ({
      product_id: row.product_id,
      qty: Number(row.qty),
      unit_price: Number(row.unit_price || 0),
      warehouse_id: row.warehouse_id || null,
      remark: row.remark || null,
    }))
  }
  for (const [key, value] of Object.entries(props.modelValue ?? {})) {
    payload[key] = value === '' ? null : value
  }
  return payload
}

/** 表头必填字段的友好提示（真实校验仍在后端） */
function validateExtra(payload: Dict): boolean {
  for (const rule of props.extraRequired) {
    if (!payload[rule.key]) {
      ElMessage.warning(`请选择/填写${rule.label}`)
      return false
    }
  }
  return true
}

/** 保存（可选随后提交） */
async function save(thenSubmit = false) {
  if (!editable.value) {
    ElMessage.warning('当前状态不可编辑')
    return
  }
  if (!validate()) return
  const payload = buildPayload()
  if (!validateExtra(payload)) return
  saving.value = true
  try {
    const doc = isEdit.value && docId.value
      ? await updateDoc(props.api, docId.value, payload)
      : await createDoc(props.api, payload)
    ElMessage.success(isEdit.value ? '已保存' : `已创建 ${doc.doc_no}`)
    emit('saved', doc)
    if (thenSubmit && canSubmit.value) {
      await docAction(props.api, doc.id, 'submit')
      ElMessage.success('已提交审核')
    }
    if (props.redirectAfterSave) router.push({ name: props.listRoute })
  } catch {
    // 422 业务校验由拦截器提示
  } finally {
    saving.value = false
  }
}

/** 打印当前单据（后端返回可打印 HTML） */
async function doPrint() {
  if (!docId.value) {
    ElMessage.warning('请先保存单据再打印')
    return
  }
  try {
    await openDocPrint(`${props.printApi || props.api}/${docId.value}/print`)
  } catch {
    // 拦截器已提示
  }
}

function back() {
  router.push({ name: props.listRoute })
}

onMounted(async () => {
  try {
    contracts.value = props.contractSource === 'sales'
      ? await fetchSalesContractOptions()
      : await fetchPurchaseContractOptions()
  } catch {
    contracts.value = []
  }
  await load()
})

defineExpose({ patchExtra, items, header, load, detail, editable })
</script>

<template>
  <div v-loading="loading">
    <el-card shadow="never" class="mb">
      <template #header>
        <div class="head">
          <div>
            <span class="title">{{ isEdit ? `编辑${kindLabel}` : `新增${kindLabel}` }}</span>
            <span v-if="detail" class="subtitle">{{ detail.doc_no }}</span>
            <DocStatusTag v-if="detail" class="ml" :status="detail.status" :label="detail.status_label" />
          </div>
          <div>
            <el-button v-if="printable && detail" @click="doPrint">
              <el-icon><Printer /></el-icon>打印
            </el-button>
            <el-button @click="back">返回列表</el-button>
          </div>
        </div>
      </template>

      <el-alert v-if="detail && !detail.editable" type="info" :closable="false" show-icon class="mb"
                title="当前状态不可编辑（仅草稿可修改）；如需修改请先反审核。" />
      <el-alert v-if="detail?.posted" type="success" :closable="false" show-icon class="mb"
                title="该单据已过账：审核即写入库存流水，反审核会自动红冲。" />

      <el-form label-width="100px" :disabled="!editable">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="单据日期" required>
              <el-date-picker v-model="header.doc_date" type="date" value-format="YYYY-MM-DD"
                              style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="关联合同">
              <el-select v-model="header.contract_id" filterable clearable
                         :placeholder="contractSource === 'sales' ? '可关联销售合同' : '可关联采购合同'"
                         style="width: 100%">
                <el-option v-for="c in contracts" :key="c.id"
                           :label="`${c.contract_no} · ${c.name}`" :value="c.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="经办人">
              <el-input-number v-model="header.handler_user_id" :min="1" :controls="false"
                               placeholder="留空默认当前用户" style="width: 100%" />
            </el-form-item>
          </el-col>
          <slot name="header" :header="header" :patch="patchExtra" :extra="extra" :detail="detail" />
          <el-col :span="24">
            <el-form-item label="备注">
              <el-input v-model="header.remark" type="textarea" :rows="2" maxlength="200" show-word-limit />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="head">
          <span class="title">行项明细</span>
          <div class="toolbar">
            <slot name="items-toolbar" :detail="detail" :editable="editable" :reload="load" :items="items" />
          </div>
        </div>
      </template>
      <slot name="items" :items="items" :readonly="!editable || !itemsEditable" :editable="editable">
        <DocItemsTable :items="items" :readonly="!editable || !itemsEditable"
                       :show-warehouse="showWarehouse" :show-price="showPrice" :extra-cols="extraCols" />
      </slot>
    </el-card>

    <div class="footer">
      <el-button @click="back">返回</el-button>
      <el-button v-if="editable && canSave" type="primary" plain :loading="saving"
                 @click="save(false)">保存草稿</el-button>
      <el-button v-if="editable && canSave && canSubmit && submitItems" type="primary" :loading="saving"
                 @click="save(true)">保存并提交</el-button>
      <slot name="actions" :detail="detail" :editable="editable" :reload="load" :saving="saving" />
      <span v-if="!canSave" class="gray">你没有该单据的编辑权限，仅可查看。</span>
    </div>
  </div>
</template>

<style scoped>
.mb { margin-bottom: 12px; }
.ml { margin-left: 8px; }
.head { display: flex; align-items: center; justify-content: space-between; }
.toolbar { display: flex; align-items: center; gap: 8px; }
.title { font-weight: 600; font-size: 15px; }
.subtitle { margin-left: 10px; color: #909399; font-size: 12.5px; }
.footer { margin-top: 12px; display: flex; align-items: center; gap: 8px; }
.gray { color: #909399; font-size: 12.5px; margin-left: 8px; }
</style>
