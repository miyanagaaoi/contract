<script setup lang="ts">
/**
 * 合同正文与签署（CR-045/049/054）：与模板页一致的左右两栏——
 * 左：正文（预览 A4 / 富文本编辑）；右：合同信息 + 模板与字段 + 签署操作。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import ContractRichEditor from '@/components/contract/ContractRichEditor.vue'
import {
  fetchContractBody, fetchContractTemplates, saveContractBody, saveContractBodyHtml,
  signContract, uploadCounterpartScan, type Dict,
} from '@/api'

const route = useRoute()
const router = useRouter()
const contractId = Number(route.params.id)
const loading = ref(false)
const templates = ref<Dict[]>([])
const body = ref<Dict>({})
const templateId = ref<number | null>(null)
const values = ref<Dict>({})
const selected = computed(() => templates.value.find((t) => t.id === templateId.value))

async function load() {
  loading.value = true
  try {
    const [t, b] = await Promise.all([fetchContractTemplates(), fetchContractBody(contractId)])
    templates.value = (t.items || []) as Dict[]
    body.value = b
    templateId.value = b.template_id || null
    values.value = { ...(b.field_values || {}) }
    prefillFromContract()
  } finally { loading.value = false }
}

const AUTO_FIELD_KEYS: Record<string, string> = {
  contract_no: 'contract_no', contract_name: 'name', name: 'name',
  contract_type: 'contract_type', type: 'contract_type',
  party_a: 'party_a', party_b: 'party_b', sign_date: 'sign_date',
  owner_name: 'owner_name', remark: 'remark',
  amount: 'amount', total_amount: 'amount', contract_amount: 'amount',
}
const AUTO_FIELD_LABELS: Record<string, string> = {
  合同编号: 'contract_no', 合同名称: 'name',
  甲方名称: 'party_a', 甲方: 'party_a', 购货方: 'party_a',
  乙方名称: 'party_b', 乙方: 'party_b', 销货方: 'party_b',
  签订日期: 'sign_date', 合同金额: 'amount', 合同总金额: 'amount', 经办人: 'owner_name',
}

function bodyFieldValue(attr: string): string {
  const v = (body.value as Dict)[attr]
  if (v === null || v === undefined) return ''
  if (attr === 'amount') return String(v)
  return String(v)
}

/** 已填合同信息自动带进正文字段（合同编号/甲乙方/签订日期/金额等） */
function prefillFromContract() {
  const tpl = selected.value
  if (!tpl) return
  for (const f of tpl.fields || []) {
    if (String(values.value[f.key] ?? '').trim()) continue
    const attr = AUTO_FIELD_KEYS[String(f.key)] || AUTO_FIELD_LABELS[String(f.label || '').trim()]
    if (!attr) continue
    const v = bodyFieldValue(attr)
    if (v) values.value[f.key] = v
  }
}

async function saveBody() {
  if (!templateId.value) { ElMessage.warning('请选择模板'); return }
  body.value = await saveContractBody(contractId, {
    template_id: templateId.value, field_values: values.value })
  ElMessage.success('合同正文已生成（快照保存）')
}

async function onSign() {
  await ElMessageBox.confirm('签署后正文只读、不可再修改，确认我方签署？', '我方签署', { type: 'warning' })
  body.value = await signContract(contractId)
  ElMessage.success('我方已签署')
}

async function uploadScan(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const r = await uploadCounterpartScan(contractId, file)
  body.value = r as Dict
  ElMessage.success('对方签署件已上传，合同已生效')
}

// 编辑正文（签署前）：生成后可直接调整表格/排版
const editing = ref(false)
const editHtml = ref('')

function startEdit() {
  editHtml.value = body.value.body_html || ''
  editing.value = true
}

async function saveEdit() {
  body.value = await saveContractBodyHtml(contractId, editHtml.value)
  editing.value = false
  ElMessage.success('正文已保存（可继续签署）')
}

/** 打印/另存 PDF：只输出正文，不带侧栏/顶栏（避免“预览了整个网页”） */
function printBody() {
  const content = body.value.body_html || ''
  if (!content) { ElMessage.warning('尚未生成正文'); return }
  const sign = body.value.sign_status !== 'none'
    ? `<div class="sign-area"><div>我方（签字）：${body.value.our_signed_name || ''}</div>` +
      `<div>签署时间：${body.value.our_signed_at || ''}</div></div>`
    : ''
  const w = window.open('', '_blank', 'width=900,height=1000')
  if (!w) { ElMessage.warning('浏览器拦截了打印窗口，请允许弹窗后重试'); return }
  w.document.write(`<!doctype html><html><head><meta charset="utf-8">
    <title>${body.value.contract_no || '合同正文'}</title>
    <style>
      @page { size: A4; margin: 18mm; }
      body { margin: 0; font-family: "SimSun", "宋体", "PingFang SC", serif; font-size: 14px; line-height: 1.8; }
      .a4 { max-width: 21cm; margin: 0 auto; }
      h1 { text-align: center; font-size: 22px; margin: 0 0 18px; }
      h2 { font-size: 16px; margin: 14px 0 8px; }
      table { border-collapse: collapse; width: 100%; margin: 8px 0; }
      td, th { border: 1px solid #333; padding: 6px 8px; vertical-align: top; }
      thead th { background: #f2f2f2; }
      tfoot td { background: #f7f7f7; }
      img { max-width: 100%; }
      .sign-area { margin-top: 48px; display: flex; gap: 80px; }
    </style></head><body><div class="a4">${content}${sign}</div></body></html>`)
  w.document.close()
  w.focus()
  setTimeout(() => { w.print() }, 400)
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <el-card shadow="never">
      <div class="bar no-print">
        <b>合同正文与签署</b>
        <span class="tip">{{ body.contract_no }} · {{ body.name }}</span>
        <span style="flex: 1"></span>
        <el-tag :type="{ none: 'info', our_signed: 'warning', completed: 'success' }[body.sign_status] || 'info'">
          {{ body.sign_status_label }}
        </el-tag>
        <el-button size="small" @click="router.push({ name: 'contract-templates' })">模板管理</el-button>
        <el-button v-if="body.body_html && body.sign_status === 'none' && !editing"
                   size="small" type="primary" plain @click="startEdit">编辑正文/表格</el-button>
        <template v-if="editing">
          <el-button size="small" type="primary" @click="saveEdit">保存正文</el-button>
          <el-button size="small" @click="editing = false">取消</el-button>
        </template>
        <el-button size="small" @click="printBody">打印 / 另存 PDF</el-button>
      </div>
    </el-card>

    <el-row :gutter="12" style="margin-top: 12px">
      <!-- 左：正文 -->
      <el-col :span="17">
        <el-card shadow="never">
          <ContractRichEditor v-if="editing" v-model="editHtml" :items-table="true" />
          <div class="a4" v-else-if="body.body_html">
            <div v-html="body.body_html"></div>
            <div class="sign-area" v-if="body.sign_status !== 'none'">
              <div>我方（签字）：{{ body.our_signed_name }}</div>
              <div>签署时间：{{ body.our_signed_at }}</div>
            </div>
          </div>
          <el-empty v-else description="尚未生成正文：右侧选择模板并点击「生成/刷新正文」" />
        </el-card>
      </el-col>

      <!-- 右：合同信息 + 模板与字段 + 签署 -->
      <el-col :span="7">
        <el-card shadow="never" class="side-card">
          <b>合同信息</b>
          <el-descriptions :column="1" size="small" border class="mt8">
            <el-descriptions-item label="合同编号">{{ body.contract_no || '—' }}</el-descriptions-item>
            <el-descriptions-item label="合同名称">{{ body.name || '—' }}</el-descriptions-item>
            <el-descriptions-item label="签署状态">{{ body.sign_status_label }}</el-descriptions-item>
            <el-descriptions-item label="我方签署人">{{ body.our_signed_name || '—' }}</el-descriptions-item>
          </el-descriptions>

          <el-divider content-position="left">模板与字段</el-divider>
          <div class="no-print">
            <el-select v-model="templateId" filterable clearable placeholder="选择合同模板"
                       style="width: 100%" :disabled="body.sign_status !== 'none'">
              <el-option v-for="t in templates" :key="t.id" :label="`${t.name}（${t.contract_type}）`"
                         :value="t.id" />
            </el-select>
            <el-button class="mt8" type="primary" style="width: 100%"
                       :disabled="body.sign_status !== 'none' || !templateId" @click="saveBody">
              生成/刷新正文
            </el-button>
          </div>
          <el-form v-if="selected && body.sign_status === 'none'" label-position="top"
                   class="no-print mt8">
            <el-form-item v-for="f in (selected.fields || [])" :key="f.key" :label="f.label"
                          :required="f.required">
              <el-select v-if="f.type === 'select'" v-model="values[f.key]" style="width: 100%">
                <el-option v-for="o in (f.options || [])" :key="o" :label="o" :value="o" />
              </el-select>
              <el-input v-else-if="f.type === 'textarea'" v-model="values[f.key]" type="textarea"
                        :rows="2" :placeholder="f.placeholder || ''" />
              <el-input-number v-else-if="f.type === 'number'" v-model="values[f.key]"
                               :controls="false" style="width: 100%" />
              <el-date-picker v-else-if="f.type === 'date'" v-model="values[f.key]" type="date"
                              value-format="YYYY-MM-DD" style="width: 100%" />
              <el-input v-else v-model="values[f.key]" :placeholder="f.placeholder || ''" />
            </el-form-item>
          </el-form>
          <div class="tip">标的物表格与金额大写会在生成时按“合同行项 / 合同金额”自动填充。</div>

          <el-divider content-position="left">签署</el-divider>
          <div class="no-print">
            <el-button v-if="body.body_html && body.sign_status === 'none'" type="warning"
                       style="width: 100%" @click="onSign">
              我方在线签署（使用我的手写签名）
            </el-button>
            <template v-if="body.sign_status === 'our_signed'">
              <el-button type="success" style="width: 100%"
                         @click="() => (document.getElementById('scan-input') as HTMLInputElement)?.click()">
                上传对方签署扫描件（置生效）
              </el-button>
              <input id="scan-input" type="file" accept=".pdf,.png,.jpg,.jpeg" style="display:none"
                     @change="uploadScan" />
            </template>
            <div v-if="body.our_signed_name" class="tip mt8">我方签署人：{{ body.our_signed_name }}
              （{{ body.our_signed_at }}）</div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.bar { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }
.tip { color: var(--el-text-color-secondary); font-size: 12px; }
.mt8 { margin-top: 8px; }
.side-card { position: sticky; top: 8px; }
.a4 { max-width: 21cm; min-height: 29.7cm; margin: 0 auto; padding: 2cm 1.6cm;
  background: #fff; box-shadow: 0 0 8px rgba(0, 0, 0, .12); }
.a4 :deep(h1) { text-align: center; font-size: 22px; margin-bottom: 18px; }
.a4 :deep(table) { border-collapse: collapse; width: 100%; margin: 8px 0; }
.a4 :deep(td), .a4 :deep(th) { border: 1px solid #cbd2da; padding: 6px 8px; vertical-align: top; }
.a4 :deep(tfoot td) { background: #f6f7f9; }
.a4 :deep(img) { max-width: 100%; }
.sign-area { margin-top: 48px; display: flex; gap: 80px; }
@media print {
  .no-print { display: none !important; }
  .a4 { box-shadow: none; margin: 0; }
}
</style>
