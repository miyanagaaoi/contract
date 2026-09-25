<script setup lang="ts">
/**
 * 树形主数据通用页（T-V2-15）：组织架构（`/api/system/org-units`）与商品类型（`/api/master/product-types`）复用。
 *
 * 交互：左侧树选择节点 → 右侧表单编辑；支持新增根节点 / 新增子节点 / 停用启用 / 删除。
 * 删除校验（有子节点、被账号或物料引用时拒绝）由后端保证，前端只展示提示。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  createMasterItem,
  deleteMasterItem,
  fetchMasterList,
  setMasterStatus,
  updateMasterItem,
  type Dict,
} from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { MasterField } from '@/types/master'

const props = withDefaults(defineProps<{
  title: string
  subtitle?: string
  api: string
  permView: string
  permEdit: string
  nodeLabel: string
  fields: MasterField[]
  /** 额外枚举（如组织类型列表），以 meta 键注入表单 */
  metaOptions?: Record<string, { label: string; value: string }[]>
}>(), { subtitle: '', metaOptions: () => ({}) })

const auth = useAuthStore()
const canEdit = computed(() => auth.hasPerm(props.permEdit))

const tree = ref<Dict[]>([])
const flat = ref<Dict[]>([])
const loading = ref(false)
const selected = ref<Dict | null>(null)
const treeRef = ref()
const filterText = ref('')

const form = reactive<Dict>({})
const creating = ref(false)
const saving = ref(false)

const treeProps = { label: 'name', children: 'children' }

async function load(keepSelection = false) {
  loading.value = true
  try {
    const data = await fetchMasterList(props.api, { include_disabled: true })
    tree.value = data.tree ?? []
    flat.value = data.items ?? []
    if (keepSelection && selected.value) {
      const again = flat.value.find((i) => i.id === selected.value?.id)
      selected.value = again ?? null
    }
  } finally {
    loading.value = false
  }
}

function fillForm(node: Dict | null) {
  for (const key of Object.keys(form)) delete form[key]
  for (const f of props.fields) {
    if (node) form[f.prop] = node[f.prop] ?? (f.type === 'switch' ? true : '')
    else form[f.prop] = f.type === 'switch' ? true : f.type === 'number' ? 0 : ''
  }
}

function onSelect(node: Dict) {
  if (!node) return
  selected.value = node
  creating.value = false
  fillForm(node)
}

function startCreateRoot() {
  selected.value = null
  creating.value = true
  treeRef.value?.setCurrentKey?.(null)
  fillForm(null)
}

function startCreateChild() {
  if (!selected.value) return ElMessage.warning(`请先选择上级${props.nodeLabel}`)
  creating.value = true
  const parentId = selected.value.id
  fillForm(null)
  form.parent_id = parentId
}

function cancelEdit() {
  creating.value = false
  onSelect(selected.value as Dict)
}

async function save() {
  for (const f of props.fields) {
    if (f.required && !String(form[f.prop] ?? '').trim()) {
      ElMessage.warning(`请填写「${f.label}」`)
      return
    }
  }
  saving.value = true
  try {
    const payload: Dict = { ...form }
    if (creating.value) {
      await createMasterItem(props.api, payload)
      ElMessage.success(`已新增${props.nodeLabel}`)
    } else if (selected.value) {
      await updateMasterItem(props.api, selected.value.id, payload)
      ElMessage.success(`已保存${props.nodeLabel}`)
    }
    creating.value = false
    await load()
    if (selected.value) onSelect(flat.value.find((i) => i.id === selected.value?.id) || selected.value)
  } catch {
    // 拦截器已提示
  } finally {
    saving.value = false
  }
}

async function toggleStatus() {
  if (!selected.value) return
  const target = selected.value
  const next = !target.enabled
  try {
    await ElMessageBox.confirm(`确定要${next ? '启用' : '停用'}「${target.name}」吗？`,
      '提示', { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' })
  } catch {
    return
  }
  await setMasterStatus(props.api, target.id, next)
  ElMessage.success(next ? '已启用' : '已停用')
  await load(true)
  if (selected.value) onSelect(selected.value)
}

async function remove() {
  if (!selected.value) return
  const target = selected.value
  try {
    await ElMessageBox.confirm(`确定要删除「${target.name}」吗？`, '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
  } catch {
    return
  }
  try {
    await deleteMasterItem(props.api, target.id)
    ElMessage.success('已删除')
    selected.value = null
    fillForm(null)
    await load()
  } catch {
    // 422 提示（有子节点/被引用）
  }
}

function filterNode(value: string, data: Dict) {
  if (!value) return true
  return String(data.name || '').includes(value) || String(data.code || '').includes(value)
}

function fieldOptions(f: MasterField) {
  if (f.type === 'select' && props.metaOptions[f.prop]) return props.metaOptions[f.prop]
  return f.options || []
}

onMounted(async () => {
  await load()
  fillForm(null)
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="head">
        <div>
          <span class="title">{{ title }}</span>
          <span v-if="subtitle" class="subtitle">{{ subtitle }}</span>
        </div>
        <div v-if="canEdit">
          <el-button @click="startCreateRoot">新增根{{ nodeLabel }}</el-button>
          <el-button type="primary" @click="startCreateChild">新增子{{ nodeLabel }}</el-button>
        </div>
      </div>
    </template>

    <el-row :gutter="16">
      <el-col :span="10">
        <el-input v-model="filterText" placeholder="按名称/编码过滤" clearable size="small" class="mb8" />
        <el-tree ref="treeRef" v-loading="loading" :data="tree" :props="treeProps" node-key="id"
                 highlight-current default-expand-all :expand-on-click-node="false"
                 :filter-node-method="filterNode" @node-click="onSelect">
          <template #default="{ data }">
            <span class="node">
              <span>{{ data.name }}</span>
              <el-tag v-if="data.code" size="small" type="info" class="node-code">{{ data.code }}</el-tag>
              <el-tag v-if="data.enabled === false" size="small" type="info">停用</el-tag>
              <el-tag v-if="data.product_count" size="small" type="success">{{ data.product_count }} 物料</el-tag>
              <el-tag v-if="data.user_count" size="small" type="warning">{{ data.user_count }} 账号</el-tag>
            </span>
          </template>
        </el-tree>
      </el-col>

      <el-col :span="14">
        <el-empty v-if="!selected && !creating" :description="`请选择左侧${nodeLabel}，或点击右上角新增`" />
        <el-form v-else label-width="110px" class="detail">
          <div class="detail-head">
            <span>{{ creating ? `新增${nodeLabel}` : `编辑${nodeLabel}：${selected?.name}` }}</span>
            <el-tag v-if="!creating && selected" :type="selected.enabled ? 'success' : 'info'" size="small">
              {{ selected.enabled ? '启用' : '停用' }}
            </el-tag>
          </div>
          <el-row :gutter="12">
            <el-col v-for="f in fields" :key="f.prop" :span="f.span || 12">
              <el-form-item :label="f.label" :required="f.required">
                <el-input v-if="!f.type || f.type === 'input'" v-model="form[f.prop]"
                          :disabled="!canEdit" :placeholder="f.placeholder" />
                <el-input v-else-if="f.type === 'textarea'" v-model="form[f.prop]" type="textarea"
                          :rows="2" :disabled="!canEdit" />
                <el-input-number v-else-if="f.type === 'number'" v-model="form[f.prop]" :controls="false"
                                 :disabled="!canEdit" style="width: 100%" />
                <el-switch v-else-if="f.type === 'switch'" v-model="form[f.prop]" :disabled="!canEdit" />
                <el-select v-else-if="f.type === 'select'" v-model="form[f.prop]" :disabled="!canEdit"
                           style="width: 100%">
                  <el-option v-for="o in fieldOptions(f)" :key="o.value" :label="o.label" :value="o.value" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <div v-if="canEdit" class="actions">
            <el-button type="primary" :loading="saving" @click="save">保存</el-button>
            <el-button v-if="creating" @click="cancelEdit">取消</el-button>
            <template v-else-if="selected">
              <el-button :type="selected.enabled ? 'warning' : 'success'" @click="toggleStatus">
                {{ selected.enabled ? '停用' : '启用' }}
              </el-button>
              <el-button type="danger" @click="remove">删除</el-button>
            </template>
          </div>
        </el-form>
      </el-col>
    </el-row>
  </el-card>
</template>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; }
.title { font-weight: 600; font-size: 15px; }
.subtitle { margin-left: 10px; color: #909399; font-size: 12.5px; }
.mb8 { margin-bottom: 8px; }
.node { display: inline-flex; align-items: center; gap: 6px; }
.node-code { margin-left: 2px; }
.detail-head { display: flex; align-items: center; gap: 10px; font-weight: 600; margin-bottom: 12px; }
.actions { margin-top: 8px; }
</style>
