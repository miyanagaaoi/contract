<script setup lang="ts">
/**
 * 合同模板管理（CR-045 / CR-049）：左富文本正文 + 右字段设计（属性/插入），支持导入 Word。
 * 字段占位符在正文中显示为【字段名称】，保存为 <span data-key> 令牌（后端渲染两种格式兼容）。
 */
import { nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import ContractRichEditor from '@/components/contract/ContractRichEditor.vue'
import {
  createContractTemplate, deleteContractTemplate, fetchContractTemplates,
  importContractTemplateDocx, updateContractTemplate, type Dict,
} from '@/api'

const loading = ref(false)
const templates = ref<Dict[]>([])
const fieldTypes = ref<Dict[]>([])
const editorRef = ref<InstanceType<typeof ContractRichEditor> | null>(null)
const form = ref<Dict>({ id: null, name: '', contract_type: '采购', description: '', body_html: '', fields: [] })

/** 通用项目：新建模板时默认带上（可按需删改） */
const COMMON_FIELDS: Dict[] = [
  { key: 'service_content', label: '服务内容', type: 'textarea', width: 'full', required: true, placeholder: '' },
  { key: 'party_a_sign_date', label: '甲方签订日期', type: 'date', width: 'half', required: false, placeholder: '' },
  { key: 'party_b_sign_date', label: '乙方签订日期', type: 'date', width: 'half', required: false, placeholder: '' },
  { key: 'start_date', label: '开始日期', type: 'date', width: 'half', required: false, placeholder: '' },
  { key: 'end_date', label: '结束日期', type: 'date', width: 'half', required: false, placeholder: '' },
  { key: 'pay_date', label: '付款日期', type: 'date', width: 'half', required: false, placeholder: '' },
]

function addCommonFields() {
  for (const f of COMMON_FIELDS) {
    if (!form.value.fields.some((x: Dict) => x.key === f.key)) {
      form.value.fields.push(JSON.parse(JSON.stringify(f)))
    }
  }
}

async function load() {
  loading.value = true
  try {
    const data = await fetchContractTemplates()
    templates.value = (data.items || []) as Dict[]
    fieldTypes.value = (data.field_types || []) as Dict[]
  } finally { loading.value = false }
}

function reset() {
  form.value = {
    id: null, name: '', contract_type: '采购', description: '',
    body_html: '<h1>合同标题</h1>'
      + '<p>合同编号：{{contract_no}}</p>'
      + '<p>甲方：{{party_a}}　　乙方：{{party_b}}</p>'
      + '<p>签订日期：{{sign_date}}</p>'
      + '<p>合同金额：{{amount_total}} 元（大写：{{amount_words}}）</p>',
    fields: JSON.parse(JSON.stringify(COMMON_FIELDS)),
  }
}

function edit(t: Dict) {
  form.value = {
    id: t.id, name: t.name, contract_type: t.contract_type,
    description: t.description || '', body_html: t.body_html,
    fields: JSON.parse(JSON.stringify(t.fields || [])),
  }
  nextTick(() => editorRef.value?.setContent(t.body_html || ''))
}

let seq = 0
function addField() {
  seq += 1
  form.value.fields.push({
    key: `field_${Date.now().toString(36)}${seq}`, label: '', type: 'text',
    width: 'half', required: false, placeholder: '',
  })
}
function delField(i: number) { form.value.fields.splice(i, 1) }
function moveField(i: number, delta: number) {
  const j = i + delta
  if (j < 0 || j >= form.value.fields.length) return
  const [item] = form.value.fields.splice(i, 1)
  form.value.fields.splice(j, 0, item)
}
function insertToBody(f: Dict) {
  if (!f.label) { ElMessage.warning('请先填写字段名称'); return }
  editorRef.value?.insertField(f.key, f.label)
}

async function save() {
  if (!form.value.name) { ElMessage.warning('模板名称必填'); return }
  if (form.value.id) await updateContractTemplate(form.value.id, form.value)
  else await createContractTemplate(form.value)
  ElMessage.success('模板已保存')
  await load()
}

async function remove(t: Dict) {
  await ElMessageBox.confirm(`删除模板「${t.name}」？已生成的合同正文不受影响（快照）。`, '删除模板',
    { type: 'warning' })
  await deleteContractTemplate(t.id)
  ElMessage.success('已删除')
  await load()
  if (form.value.id === t.id) reset()
}

// ---------- 导入 Word ----------
const wordInput = ref<HTMLInputElement | null>(null)

async function onWordPicked(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (form.value.body_html && form.value.body_html.replace(/<[^>]+>/g, '').trim()) {
    try {
      await ElMessageBox.confirm('导入 Word 将覆盖当前正文内容，继续？', '导入 Word', { type: 'warning' })
    } catch { return }
  }
  const data = await importContractTemplateDocx(file)
  form.value.body_html = data.html || ''
  await nextTick()
  // 强制回填编辑器：否则光标还停在编辑区内时 watch 会跳过同步，表现为“导入好几遍才显示”
  editorRef.value?.setContent(data.html || '')
  if ((data.warnings || []).length) ElMessage.warning(data.warnings.join('；'))
  ElMessage.success('Word 内容已导入（保留标题/段落/表格/图片），可继续插入字段占位符')
}

onMounted(async () => { await load(); reset() })
</script>

<template>
  <div v-loading="loading" class="tpl-page">
    <el-card shadow="never">
      <div class="bar">
        <b>合同模板</b>
        <span class="tip">左：富文本正文（字段显示为【名称】）；右：字段设计（属性 + 插入正文）</span>
        <span style="flex: 1"></span>
        <el-select v-model="form.id" clearable placeholder="选择模板编辑" style="width: 220px"
                   @change="(id: number) => { const t = templates.find((x) => x.id === id); if (t) edit(t) }">
          <el-option v-for="t in templates" :key="t.id" :label="t.name" :value="t.id" />
        </el-select>
        <el-button @click="reset">新建模板</el-button>
        <el-button v-if="form.id" type="danger" plain @click="remove(form)">删除</el-button>
      </div>

      <el-row :gutter="12" class="meta">
        <el-col :span="7"><el-form-item label="模板名称" required>
          <el-input v-model="form.name" maxlength="128" /></el-form-item></el-col>
        <el-col :span="3"><el-form-item label="分类">
          <el-select v-model="form.contract_type" style="width: 100%">
            <el-option v-for="t in ['采购', '销售', '框架', '补充协议']" :key="t" :label="t" :value="t" />
          </el-select></el-form-item></el-col>
        <el-col :span="14"><el-form-item label="描述">
          <el-input v-model="form.description" maxlength="200" /></el-form-item></el-col>
      </el-row>

      <div class="bar">
        <el-button @click="wordInput?.click()">导入 Word 文档</el-button>
        <input ref="wordInput" type="file" accept=".docx" style="display:none" @change="onWordPicked" />
        <span style="flex: 1"></span>
        <el-button type="primary" @click="save">保存模板</el-button>
      </div>
    </el-card>

    <el-row :gutter="12">
      <el-col :span="17">
        <el-card shadow="never">
          <div class="tip" style="margin-bottom:6px">
            标的物表格：点工具栏「插入标的物表格」放在“合同标的”位置；这里只显示令牌，
            新增合同并录入行项后生成正文时，会自动替换成该合同的行项表格（签署前可编辑调整）。
          </div>
          <ContractRichEditor ref="editorRef" v-model="form.body_html" :fields="form.fields"
                               :items-table="true" />
        </el-card>
      </el-col>
      <el-col :span="7">
        <el-card shadow="never" class="fields-card">
          <div class="bar">
            <b>字段设计</b>
            <span class="tip">点「插入正文」把字段放到光标处</span>
            <span style="flex: 1"></span>
            <el-button size="small" type="primary" plain @click="addField">+ 新增字段</el-button>
          </div>
          <el-empty v-if="!form.fields.length" description="还没有字段，先点「新增字段」" :image-size="60" />
          <div v-for="(f, i) in form.fields" :key="f.key" class="field-card">
            <div class="field-card__head">
              <el-input v-model="f.label" placeholder="字段名称（如：甲方名称）" size="small" />
              <el-button link size="small" @click="moveField(i, -1)">↑</el-button>
              <el-button link size="small" @click="moveField(i, 1)">↓</el-button>
              <el-button link type="danger" size="small" @click="delField(i)">删</el-button>
            </div>
            <el-row :gutter="6" class="mt6">
              <el-col :span="13">
                <el-select v-model="f.type" size="small" style="width: 100%">
                  <el-option v-for="t in fieldTypes" :key="t.value" :label="t.label" :value="t.value" />
                </el-select>
              </el-col>
              <el-col :span="11">
                <el-select v-model="f.width" size="small" style="width: 100%">
                  <el-option label="半行" value="half" />
                  <el-option label="整行" value="full" />
                </el-select>
              </el-col>
            </el-row>
            <el-input v-model="f.placeholder" size="small" placeholder="填写提示（可留空）" class="mt6" />
            <div class="field-card__foot">
              <el-checkbox v-model="f.required" size="small">必填</el-checkbox>
              <el-button link type="primary" size="small" @click="insertToBody(f)">插入正文</el-button>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.tpl-page { display: flex; flex-direction: column; gap: 12px; }
.bar { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }
.tip { color: var(--el-text-color-secondary); font-size: 12px; }
.meta { margin-bottom: 2px; }
.mt6 { margin-top: 6px; }
.fields-card { max-height: 70vh; overflow-y: auto; }
.field-card { border: 1px solid var(--el-border-color-lighter); border-radius: 6px;
  padding: 8px; margin-bottom: 8px; background: var(--el-fill-color-blank); }
.field-card__head { display: flex; gap: 4px; align-items: center; }
.field-card__foot { display: flex; justify-content: space-between; align-items: center; margin-top: 6px; }
</style>
