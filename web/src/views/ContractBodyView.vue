<script setup lang="ts">
/**
 * 合同正文与签署（CR-045）：选模板 → 填字段 → 生成正文快照 → 我方在线签 → 上传对方扫描件生效。
 * 模板维护（仅管理员）：名称/类型/富文本 HTML/字段定义。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  createContractTemplate, fetchContractBody, fetchContractTemplates, saveContractBody,
  signContract, updateContractTemplate, uploadCounterpartScan, type Dict,
} from '@/api'

const route = useRoute()
const contractId = Number(route.params.id)
const loading = ref(false)
const templates = ref<Dict[]>([])
const fieldTypes = ref<Dict[]>([])
const body = ref<Dict>({})
const templateId = ref<number | null>(null)
const values = ref<Dict>({})
const selected = computed(() => templates.value.find((t) => t.id === templateId.value))

async function load() {
  loading.value = true
  try {
    const [t, b] = await Promise.all([fetchContractTemplates(), fetchContractBody(contractId)])
    templates.value = (t.items || []) as Dict[]
    fieldTypes.value = (t.field_types || []) as Dict[]
    body.value = b
    templateId.value = b.template_id || null
    values.value = { ...(b.field_values || {}) }
  } finally { loading.value = false }
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

function printBody() { window.print() }

// ---------------- 模板维护 ----------------
const tplDlg = ref(false)
const tplForm = ref<Dict>({ id: null, name: '', contract_type: '采购', body_html: '', fields: [] })
const canManageTpl = ref(false)

async function openTpl() {
  tplDlg.value = true
  if (!tplForm.value.id) {
    tplForm.value = { id: null, name: '', contract_type: '采购',
      body_html: '<h1>合同标题</h1><p>甲方：{{party_a}}</p><p>乙方：{{party_b}}</p>',
      fields: [{ key: 'party_a', label: '甲方', type: 'text', required: true },
               { key: 'party_b', label: '乙方', type: 'text', required: true }] }
  }
}

function editTpl(t: Dict) {
  tplForm.value = { id: t.id, name: t.name, contract_type: t.contract_type,
    body_html: t.body_html, fields: JSON.parse(JSON.stringify(t.fields || [])) }
}

function addField() { tplForm.value.fields.push({ key: '', label: '', type: 'text', required: false }) }
function delField(i: number) { tplForm.value.fields.splice(i, 1) }

async function saveTpl() {
  const payload = { ...tplForm.value }
  if (tplForm.value.id) await updateContractTemplate(tplForm.value.id, payload)
  else await createContractTemplate(payload)
  ElMessage.success('模板已保存')
  tplDlg.value = false
  await load()
}

function printCss() {
  return `@media print { .no-print { display:none !important } .a4 { box-shadow:none; margin:0 } }`
}
onMounted(async () => { await load(); canManageTpl.value = true })
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
        <el-button size="small" @click="openTpl">模板管理</el-button>
        <el-button size="small" @click="printBody">打印 / 另存 PDF</el-button>
      </div>

      <div class="bar no-print">
        <span>模板</span>
        <el-select v-model="templateId" filterable clearable placeholder="选择合同模板"
                   style="width: 260px" :disabled="body.sign_status !== 'none'">
          <el-option v-for="t in templates" :key="t.id" :label="`${t.name}（${t.contract_type}）`"
                     :value="t.id" />
        </el-select>
        <el-button type="primary" :disabled="body.sign_status !== 'none' || !templateId"
                   @click="saveBody">生成/刷新正文</el-button>
      </div>

      <el-form v-if="selected && body.sign_status === 'none'" label-width="120px" class="no-print">
        <el-form-item v-for="f in (selected.fields || [])" :key="f.key" :label="f.label" :required="f.required">
          <el-select v-if="f.type === 'select'" v-model="values[f.key]" style="width: 320px">
            <el-option v-for="o in (f.options || [])" :key="o" :label="o" :value="o" />
          </el-select>
          <el-input v-else-if="f.type === 'textarea'" v-model="values[f.key]" type="textarea" :rows="3"
                    style="width: 420px" :placeholder="f.placeholder || ''" />
          <el-input-number v-else-if="f.type === 'number'" v-model="values[f.key]" :controls="false"
                           style="width: 220px" />
          <el-date-picker v-else-if="f.type === 'date'" v-model="values[f.key]" type="date"
                          value-format="YYYY-MM-DD" style="width: 220px" />
          <el-input v-else v-model="values[f.key]" style="width: 320px" :placeholder="f.placeholder || ''" />
        </el-form-item>
      </el-form>

      <div class="bar no-print">
        <el-button v-if="body.body_html && body.sign_status === 'none'" type="warning" @click="onSign">
          我方在线签署（使用我的手写签名）
        </el-button>
        <template v-if="body.sign_status === 'our_signed'">
          <el-button type="success" @click="() => (document.getElementById('scan-input') as HTMLInputElement)?.click()">
            上传对方签署扫描件（置生效）
          </el-button>
          <input id="scan-input" type="file" accept=".pdf,.png,.jpg,.jpeg" style="display:none"
                 @change="uploadScan" />
        </template>
        <span v-if="body.our_signed_name" class="tip">我方签署人：{{ body.our_signed_name }}
          （{{ body.our_signed_at }}）</span>
      </div>

      <div class="a4" v-if="body.body_html">
        <div v-html="body.body_html"></div>
        <div class="sign-area" v-if="body.sign_status !== 'none'">
          <div>我方（签字）：{{ body.our_signed_name }}</div>
          <div>签署时间：{{ body.our_signed_at }}</div>
        </div>
      </div>
      <el-empty v-else description="尚未生成正文：选择模板并点击「生成/刷新正文」" />
    </el-card>

    <el-dialog v-model="tplDlg" title="合同模板管理（仅管理员可保存）" width="860px">
      <div class="bar">
        <el-select v-model="tplForm.id" placeholder="选择模板编辑" clearable style="width: 260px"
                   @change="(id: number) => { const t = templates.find((x) => x.id === id); if (t) editTpl(t) }">
          <el-option v-for="t in templates" :key="t.id" :label="t.name" :value="t.id" />
        </el-select>
        <el-button @click="openTpl">新建模板</el-button>
      </div>
      <el-form label-width="90px">
        <el-form-item label="名称" required><el-input v-model="tplForm.name" style="width: 320px" /></el-form-item>
        <el-form-item label="合同类型">
          <el-select v-model="tplForm.contract_type" style="width: 160px">
            <el-option v-for="t in ['采购', '销售', '框架', '补充协议']" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="正文 HTML">
          <el-input v-model="tplForm.body_html" type="textarea" :rows="10" />
          <div class="tip">支持基础 HTML（h1/p/b/ul）；字段占位符写 {'{{field_key}}'}。</div>
        </el-form-item>
      </el-form>
      <el-table :data="tplForm.fields" border size="small">
        <el-table-column label="key" width="150">
          <template #default="{ row }"><el-input v-model="row.key" size="small" /></template>
        </el-table-column>
        <el-table-column label="显示名" width="150">
          <template #default="{ row }"><el-input v-model="row.label" size="small" /></template>
        </el-table-column>
        <el-table-column label="类型" width="140">
          <template #default="{ row }">
            <el-select v-model="row.type" size="small">
              <el-option v-for="t in fieldTypes" :key="t.value" :label="t.label" :value="t.value" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="必填" width="80">
          <template #default="{ row }"><el-switch v-model="row.required" /></template>
        </el-table-column>
        <el-table-column label="下拉选项（逗号分隔）">
          <template #default="{ row }">
            <el-input v-if="row.type === 'select'" size="small"
                      :model-value="(row.options || []).join(',')"
                      @update:model-value="(v: string) => row.options = v.split(',').map((s) => s.trim()).filter(Boolean)" />
          </template>
        </el-table-column>
        <el-table-column label="" width="60">
          <template #default="{ $index }">
            <el-button link type="danger" @click="delField($index)">删</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-button class="mt8" size="small" @click="addField">添加字段</el-button>
      <template #footer>
        <el-button @click="tplDlg = false">关闭</el-button>
        <el-button type="primary" @click="saveTpl">保存模板</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.bar { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
.tip { color: var(--el-text-color-secondary); font-size: 12px; }
.mt8 { margin-top: 8px; }
.a4 { max-width: 21cm; min-height: 29.7cm; margin: 0 auto; padding: 2cm 1.6cm;
  background: #fff; box-shadow: 0 0 8px rgba(0,0,0,.12); }
.a4 :deep(h1) { text-align: center; font-size: 22px; margin-bottom: 18px; }
.sign-area { margin-top: 48px; display: flex; gap: 80px; }
@media print {
  .no-print { display: none !important; }
  .a4 { box-shadow: none; margin: 0; }
}
</style>
