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
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import DocItemsTable from '@/components/doc/DocItemsTable.vue'
import DocStatusTag from '@/components/doc/DocStatusTag.vue'
import {
  createDoc,
  docAction,
  fetchDoc,
  fetchMasterOptions,
  fetchPurchaseContractOptions,
  fetchSalesContractOptions,
  openDocPrint,
  updateDoc,
  type Dict,
} from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { DocRecord } from '@/types/doc'
import { todayLocal } from '@/utils/format'
import { registerUnsavedGuard, unregisterUnsavedGuard } from '@/utils/unsaved'

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
  /** 是否显示金额相关列（单价 / 金额）；调拨单等不涉及金额的单据传 false */
  showAmount?: boolean
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
  showAmount: true,
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
const handlerOptions = ref<Dict[]>([])   // V2.1 / N1：经办人账号下拉（仅启用账号）

// ---------- 未保存离开保护（T1-1） ----------
/**
 * 脏标记：表头任一字段、行项或扩展字段变化即置位。
 *
 * 触发来源有三类：
 * 1. `header`（reactive）—— deep watch 捕获；
 * 2. 行项 —— `DocItemsTable` 在每个增删改点都 `emit('change')`，父组件监听即可，
 *    无需 deep watch 整个数组；
 * 3. 父页面通过 `v-model` 绑定的特有字段 —— 由 `setExtra` / `patchExtra` 显式标记。
 *
 * `flush: 'sync'` 是必需的：服务端回填发生在 `suppressDirty` 为真的同步区间内，
 * 默认的 pre flush 会等到区间退出后才回调，抑制标志已失效。
 */
const dirty = ref(false)
let suppressDirty = false

function markDirty(): void {
  if (!suppressDirty) dirty.value = true
}

function markClean(): void {
  dirty.value = false
}

function onItemsChange(): void {
  markDirty()
}

const header = reactive<{
  doc_date: string
  handler_user_id: number | null
  contract_id: number | null
  remark: string
}>({
  doc_date: todayLocal(),
  handler_user_id: auth.user?.id ?? null,
  contract_id: null,
  remark: '',
})

// 表头字段变化即视为脏；flush: 'sync' 才能被 suppressDirty 抑制（见上方说明）
watch(header, markDirty, { deep: true, flush: 'sync' })

/** 表头扩展字段（特有字段）：父页面用 v-model 绑定 */
const extra = computed<Dict>({
  get: () => props.modelValue ?? {},
  set: (v: Dict) => emit('update:modelValue', v),
})

function setExtra(key: string, value: unknown) {
  extra.value = { ...(props.modelValue ?? {}), [key]: value }
  markDirty()
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
  suppressDirty = true          // 服务端回填不算用户编辑
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
    suppressDirty = false
    markClean()                 // 回填完成即视为干净（与服务端一致）
  }
}

/**
 * 行项校验（T3-6）。
 *
 * 原先遇到**第一个**错误就 `ElMessage.warning` 并 return——提示一闪即逝，
 * 用户改完第一个再提交才发现第二个，长表单要来回好几轮。
 *
 * 改为一次性收集全部行错误：`rowErrors` 供表格高亮错误行，`itemErrorSummary`
 * 渲染成持久提示条，用户可以一次看全所有问题。
 *
 * 注意：空行项的 toast 文案被 e2e 断言依赖（06-purchase.spec.ts:153），故保留。
 */
const rowErrors = ref<Record<number, string>>({})

/** 校验失败的行索引（传给 DocItemsTable 做行高亮） */
const errorRows = computed(() => Object.keys(rowErrors.value).map(Number))

/** 行错误的持久文案（「第 N 行：…」按行号排序拼接） */
const itemErrorSummary = computed(() => Object.entries(rowErrors.value)
  .sort((a, b) => Number(a[0]) - Number(b[0]))
  .map(([idx, msg]) => `第 ${Number(idx) + 1} 行：${msg}`)
  .join('；'))

function validateItems(): boolean {
  if (!items.value.length) {
    rowErrors.value = {}
    ElMessage.warning('请至少添加一行行项')
    return false
  }
  const errors: Record<number, string> = {}
  items.value.forEach((row, i) => {
    if (!row.product_id) {
      errors[i] = '请选择物料'
      return
    }
    if (!(Number(row.qty) > 0)) {
      errors[i] = '数量必须大于 0'
      return
    }
    const decimals = row.uom_decimals === null || row.uom_decimals === undefined ? 2 : Number(row.uom_decimals)
    const qtyText = String(Number(row.qty))
    const dot = qtyText.indexOf('.')
    if (decimals === 0 && (dot >= 0 ? Number(qtyText.slice(dot + 1)) > 0 : false)) {
      errors[i] = '单位不支持小数，数量请填整数'
      return
    }
    if (dot >= 0 && qtyText.length - dot - 1 > decimals) {
      errors[i] = `数量小数位超过单位允许的 ${decimals} 位`
    }
  })
  rowErrors.value = errors
  return Object.keys(errors).length === 0
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
    markClean()                 // 内容已落库
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

/** 提交/保存进行中不拦截：保存流程自己会跳转 */
function hasUnsaved(): boolean {
  return dirty.value && !saving.value
}

function onBeforeUnload(e: BeforeUnloadEvent): void {
  if (!hasUnsaved()) return
  // 浏览器只在设置了 returnValue 时弹原生确认框
  e.preventDefault()
  e.returnValue = ''
}

/**
 * 未保存离开确认（T1-1）：录入几十行行项后误点「返回列表」是全项目唯一会
 * **静默丢数据**的路径。
 *
 * 注意：这里不能用 `onBeforeRouteLeave` —— 本组件是各表单页复用的**子组件**，
 * 而该守卫只对路由组件生效（子组件里调用不报错，但注册无效）。改为注册到
 * `@/utils/unsaved`，由全局 `router.beforeEach` 调用（见 router/index.ts）。
 */
async function confirmDiscard(): Promise<boolean> {
  if (!hasUnsaved()) return true
  try {
    await ElMessageBox.confirm('当前单据有未保存的修改，确定离开？', '未保存的修改', {
      type: 'warning', confirmButtonText: '离开', cancelButtonText: '留在本页',
    })
    return true
  } catch {
    return false
  }
}

onMounted(() => {
  registerUnsavedGuard(confirmDiscard)
  window.addEventListener('beforeunload', onBeforeUnload)
})
onBeforeUnmount(() => {
  unregisterUnsavedGuard()
  window.removeEventListener('beforeunload', onBeforeUnload)
})

onMounted(async () => {
  try {
    contracts.value = props.contractSource === 'sales'
      ? await fetchSalesContractOptions()
      : await fetchPurchaseContractOptions()
  } catch {
    contracts.value = []
  }
  try {
    // V2.1 / N1：经办人下拉（`/api/master/options/user`，仅返回启用账号）
    handlerOptions.value = await fetchMasterOptions('user')
  } catch {
    handlerOptions.value = []
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
              <div class="contract-input">
                <el-select v-model="header.contract_id" filterable clearable
                           :placeholder="contractSource === 'sales' ? '可关联销售合同' : '可关联采购合同'"
                           style="width: 100%">
                  <el-option v-for="c in contracts" :key="c.id"
                             :label="`${c.contract_no} · ${c.name}`" :value="c.id" />
                </el-select>
                <!--
                  单据页可在此放一个紧凑动作（如「查看合同详情」小按钮）。
                  放在选择框右侧、而不是单独占一个表单项：原先它在页面底部独占半行，
                  与它服务的「关联合同」字段隔着好几个字段，视线要来回跳。
                -->
                <slot name="contract-actions" :header="header" :detail="detail" />
              </div>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="经办人">
              <el-select v-model="header.handler_user_id" filterable clearable
                         placeholder="默认当前账号" style="width: 100%">
                <el-option v-for="u in handlerOptions" :key="u.id"
                           :label="`${u.name}（${u.username}）`" :value="u.id" />
              </el-select>
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
            <slot name="items-toolbar" :detail="detail" :editable="editable" :reload="load" :items="items"
                  :header="header" />
          </div>
        </div>
      </template>
      <!-- 行项校验的持久提示（T3-6）：替代原先一闪即逝的 toast，一次列全部问题 -->
      <el-alert v-if="itemErrorSummary" type="error" :closable="false" show-icon class="mb"
                title="行项校验未通过" :description="itemErrorSummary" />
      <slot name="items" :items="items" :readonly="!editable || !itemsEditable" :editable="editable">
        <DocItemsTable :items="items" :readonly="!editable || !itemsEditable"
                       :show-warehouse="showWarehouse" :show-price="showPrice" :show-amount="showAmount"
                       :extra-cols="extraCols"
                       :error-rows="errorRows" @change="onItemsChange" />
      </slot>
    </el-card>

    <div class="footer">
      <el-button @click="back">返回</el-button>
      <el-button v-if="editable && canSave" type="primary" plain :loading="saving" :disabled="saving"
                 @click="save(false)">保存草稿</el-button>
      <el-button v-if="editable && canSave && canSubmit && submitItems" type="primary" :loading="saving"
                 :disabled="saving" @click="save(true)">保存并提交</el-button>
      <slot name="actions" :detail="detail" :editable="editable" :reload="load" :saving="saving" />
      <span v-if="!canSave" class="gray">你没有该单据的编辑权限，仅可查看。</span>
    </div>
  </div>
</template>

<style scoped>
.mb { margin-bottom: var(--ctms-gap); }
.ml { margin-left: var(--ctms-gap-sm); }
/* 「关联合同」选择框与其右侧紧凑动作同一行（见 #contract-actions 插槽） */
.contract-input { display: flex; align-items: center; gap: var(--ctms-gap-sm); width: 100%; }
.contract-input :deep(.el-select) { flex: 1; min-width: 0; }
.contract-input :deep(.gray), .contract-input .gray { white-space: nowrap; }
.head { display: flex; align-items: center; justify-content: space-between; }
.toolbar { display: flex; align-items: center; gap: 8px; }
.title { font-weight: 600; font-size: var(--ctms-fs-md); }
.subtitle { margin-left: 10px; color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); }
.footer { margin-top: var(--ctms-gap); display: flex; align-items: center; gap: 8px; }
.gray { color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); margin-left: var(--ctms-gap-sm); }
</style>
