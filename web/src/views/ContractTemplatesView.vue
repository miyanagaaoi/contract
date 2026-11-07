<script setup lang="ts">
/**
 * 合同模板管理（CR-045）：列表 + 编辑（名称/类型/正文 HTML/字段定义）。
 * 仅管理员可保存（后端 require_superadmin），普通账号只读。
 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  createContractTemplate, deleteContractTemplate, fetchContractTemplates,
  updateContractTemplate, type Dict,
} from '@/api'

const loading = ref(false)
const templates = ref<Dict[]>([])
const fieldTypes = ref<Dict[]>([])
const form = ref<Dict>({ id: null, name: '', contract_type: '采购', body_html: '', fields: [] })

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
    id: null, name: '', contract_type: '采购',
    body_html: '<h1>合同标题</h1><p>甲方：{{party_a}}</p><p>乙方：{{party_b}}</p>',
    fields: [{ key: 'party_a', label: '甲方', type: 'text', required: true },
             { key: 'party_b', label: '乙方', type: 'text', required: true }],
  }
}

function edit(t: Dict) {
  form.value = { id: t.id, name: t.name, contract_type: t.contract_type,
    body_html: t.body_html, fields: JSON.parse(JSON.stringify(t.fields || [])) }
}

function addField() { form.value.fields.push({ key: '', label: '', type: 'text', required: false }) }
function delField(i: number) { form.value.fields.splice(i, 1) }

async function save() {
  if (!form.value.name) { ElMessage.warning('模板名称必填'); return }
  if (form.value.id) await updateContractTemplate(form.value.id, form.value)
  else await createContractTemplate(form.value)
  ElMessage.success('模板已保存')
  await load()
  reset()
}

async function remove(t: Dict) {
  await ElMessageBox.confirm(`删除模板「${t.name}」？已生成的合同正文不受影响（快照）。`, '删除模板',
    { type: 'warning' })
  await deleteContractTemplate(t.id)
  ElMessage.success('已删除')
  await load()
  if (form.value.id === t.id) reset()
}

onMounted(async () => { await load(); reset() })
</script>

<template>
  <div v-loading="loading">
    <el-card shadow="never">
      <div class="bar">
        <b>合同模板</b>
        <span class="tip">正文用 HTML 编写，字段占位符写 {'{{field_key}}'}；保存模板后到「新增合同」里选择模板生成正文。</span>
        <span style="flex: 1"></span>
        <el-button @click="reset">新建模板</el-button>
      </div>
      <el-table :data="templates" border stripe size="small" max-height="280"
                @row-click="edit">
        <el-table-column prop="name" label="模板名称" min-width="200" />
        <el-table-column prop="contract_type" label="类型" width="110" />
        <el-table-column label="字段数" width="80" align="right">
          <template #default="{ row }">{{ (row.fields || []).length }}</template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" width="160" />
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="danger" @click.stop="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" class="mt12">
      <el-form label-width="90px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" style="width: 320px" maxlength="128" />
        </el-form-item>
        <el-form-item label="合同类型">
          <el-select v-model="form.contract_type" style="width: 160px">
            <el-option v-for="t in ['采购', '销售', '框架', '补充协议']" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="正文 HTML">
          <el-input v-model="form.body_html" type="textarea" :rows="10" />
        </el-form-item>
      </el-form>
      <el-table :data="form.fields" border size="small">
        <el-table-column label="key（占位符）" width="160">
          <template #default="{ row }"><el-input v-model="row.key" size="small" /></template>
        </el-table-column>
        <el-table-column label="显示名" width="160">
          <template #default="{ row }"><el-input v-model="row.label" size="small" /></template>
        </el-table-column>
        <el-table-column label="类型" width="150">
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
      <div class="bar mt8">
        <el-button size="small" @click="addField">添加字段</el-button>
        <span style="flex: 1"></span>
        <el-button type="primary" @click="save">保存模板</el-button>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.bar { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }
.tip { color: var(--el-text-color-secondary); font-size: 12px; }
.mt8 { margin-top: 8px; }
.mt12 { margin-top: 12px; }
</style>
