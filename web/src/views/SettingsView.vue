<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createTag,
  deleteTag,
  fetchTags,
  http,
  renameTag,
  saveContractTypes,
  saveItemTypes,
  saveSubjects,
  type Dict,
} from '@/api'

const active = ref<'types' | 'subjects' | 'tags' | 'items'>('types')

// ---------- 合同类型（MVP3） ----------
const types = ref<Dict[]>([])
const typesSaving = ref(false)
async function loadTypes() {
  const { data } = await http.get('/settings/contract-types')
  types.value = data.contract_types
}
async function saveTypes() {
  if (!types.value.length) return ElMessage.warning('至少保留一个类型')
  typesSaving.value = true
  try {
    await saveContractTypes(types.value)
    ElMessage.success('合同类型已保存')
    await loadTypes()
  } catch (e) { ElMessage.error(apiError(e)) } finally { typesSaving.value = false }
}

// ---------- 我方主体码（MVP3） ----------
const subjects = ref<Dict[]>([])
const subjectsSaving = ref(false)
async function loadSubjects() {
  const { data } = await http.get('/settings/subjects')
  subjects.value = data.subjects
}
function addSubject() { subjects.value.push({ code: '', name: '' }) }
function removeSubject(i: number) { subjects.value.splice(i, 1) }
async function saveSubjectsNow() {
  subjectsSaving.value = true
  try {
    await saveSubjects(subjects.value)
    ElMessage.success('我方公司已保存')
    await loadSubjects()
  } catch (e) { ElMessage.error(apiError(e)) } finally { subjectsSaving.value = false }
}

// ---------- 标签管理 ----------
const tags = ref<Dict[]>([])
const newTagName = ref('')
async function loadTags() { tags.value = await fetchTags() }
async function addTag() {
  const name = newTagName.value.trim()
  if (!name) return
  try { await createTag(name); newTagName.value = ''; await loadTags() } catch (e) { ElMessage.error(apiError(e)) }
}
async function tagRename(tag: Dict) {
  try {
    const { value } = await ElMessageBox.prompt('新名称：', `重命名标签「${tag.name}」`, { inputValue: tag.name })
    await renameTag(tag.id, value.trim()); await loadTags()
  } catch (e) { if (e !== 'cancel' && e !== 'close') ElMessage.error(apiError(e)) }
}
async function tagRemove(tag: Dict) {
  try {
    await ElMessageBox.confirm(`删除标签「${tag.name}」？将从 ${tag.usage_count} 个合同移除`, '删除确认', { type: 'warning' })
    await deleteTag(tag.id); await loadTags()
  } catch (e) { if (e !== 'cancel' && e !== 'close') ElMessage.error(apiError(e)) }
}

// ---------- 行项类型字典 ----------
const items = ref<string[]>([])
const newItem = ref('')
const itemsSaving = ref(false)
async function loadItems() {
  const { data } = await http.get('/settings/item-types')
  items.value = data.item_types
}
function addItem() {
  const v = newItem.value.trim()
  if (v && !items.value.includes(v)) items.value.push(v)
  newItem.value = ''
}
function removeItem(i: number) { items.value.splice(i, 1) }
async function saveItemsNow() {
  itemsSaving.value = true
  try { await saveItemTypes(items.value); await loadItems(); ElMessage.success('行项类型已保存') }
  catch (e) { ElMessage.error(apiError(e)) } finally { itemsSaving.value = false }
}

function apiError(e: any): string {
  return e?.response?.data?.detail || '操作失败'
}

onMounted(async () => {
  await Promise.all([loadTypes(), loadSubjects(), loadTags(), loadItems()])
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <b>系统设置</b>
      <span class="gray" style="margin-left: 10px">合同类型 / 我方主体 / 标签 / 行项类型</span>
    </template>

    <el-tabs v-model="active">
      <!-- 合同类型 -->
      <el-tab-pane label="合同类型（编号码）" name="types">
        <el-alert type="info" :closable="false" class="mb" show-icon
          title="编号规则：类型码+主体码+年份+月份+6位序号（如 PURZC202609000001，年度递增）。"
          description="OTH 为历史“其他”类型，不参与自动编号。类型名修改后：存量合同保存时自动映射到新名，类型名标签同步。" />
        <el-table :data="types" size="small" border>
          <el-table-column label="代码" width="90">
            <template #default="{ row }"><el-input v-model="row.code" size="small" disabled /></template>
          </el-table-column>
          <el-table-column label="类型名称" min-width="150">
            <template #default="{ row }"><el-input v-model="row.label" size="small" /></template>
          </el-table-column>
          <el-table-column label="说明" min-width="180">
            <template #default="{ row }"><el-input v-model="row.note" size="small" /></template>
          </el-table-column>
          <el-table-column label="启用" width="70" align="center">
            <template #default="{ row }"><el-switch v-model="row.enabled" :disabled="row.code === 'OTH'" /></template>
          </el-table-column>
        </el-table>
        <div class="mt"><el-button type="primary" :loading="typesSaving" @click="saveTypes">保存合同类型</el-button></div>
      </el-tab-pane>

      <!-- 我方主体 -->
      <el-tab-pane label="我方公司（主体码）" name="subjects">
        <el-alert type="info" :closable="false" class="mb" show-icon title="编号的主体码取自这里；新增合同下拉选择。" />
        <el-table :data="subjects" size="small" border>
          <el-table-column label="主体码" width="120">
            <template #default="{ row }"><el-input v-model="row.code" size="small" placeholder="如 ZC" /></template>
          </el-table-column>
          <el-table-column label="公司名称" min-width="200">
            <template #default="{ row }"><el-input v-model="row.name" size="small" placeholder="如 智澈公司" /></template>
          </el-table-column>
          <el-table-column label="操作" width="80">
            <template #default="{ $index }"><el-button link type="danger" @click="removeSubject($index)">删除</el-button></template>
          </el-table-column>
        </el-table>
        <div class="mt">
          <el-button size="small" @click="addSubject">＋ 增加主体</el-button>
          <el-button type="primary" :loading="subjectsSaving" @click="saveSubjectsNow">保存</el-button>
        </div>
      </el-tab-pane>

      <!-- 标签 -->
      <el-tab-pane label="标签管理" name="tags">
        <div class="mb" style="display: flex; gap: 8px">
          <el-input v-model="newTagName" placeholder="新标签名称" style="max-width: 260px" @keyup.enter="addTag" />
          <el-button type="primary" @click="addTag">新增</el-button>
        </div>
        <el-table :data="tags" size="small" border>
          <el-table-column prop="name" label="标签" min-width="160" />
          <el-table-column prop="usage_count" label="使用合同数" width="110" align="center" />
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <el-button link type="primary" @click="tagRename(row)">改名</el-button>
              <el-button link type="danger" @click="tagRemove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 行项类型 -->
      <el-tab-pane label="行项类型字典" name="items">
        <div class="mb" style="display: flex; gap: 8px">
          <el-input v-model="newItem" placeholder="新增行项类型" style="max-width: 260px" @keyup.enter="addItem" />
          <el-button type="primary" @click="addItem">新增</el-button>
        </div>
        <el-table :data="items" size="small" border>
          <el-table-column label="类型名称" min-width="200">
            <template #default="{ row, $index }"><el-input v-model="items[$index]" size="small" /></template>
          </el-table-column>
          <el-table-column label="操作" width="80">
            <template #default="{ $index }"><el-button link type="danger" @click="removeItem($index)">删除</el-button></template>
          </el-table-column>
        </el-table>
        <div class="mt"><el-button type="primary" :loading="itemsSaving" @click="saveItemsNow">保存</el-button></div>
      </el-tab-pane>
    </el-tabs>
  </el-card>
</template>

<style scoped>
.mb { margin-bottom: 12px; }
.mt { margin-top: 12px; }
.gray { color: #909399; font-size: 13px; }
</style>
