<script setup lang="ts">
/**
 * 主数据通用维护页（T-V2-15）：配置驱动的"列表 + 表单 + 启停用 + 删除"。
 *
 * 覆盖客户、供应商、计量单位、仓库、物料 5 类档案（字段差异由 `fields` 描述）。
 * 权限由后端强制校验（AC-V2-41），前端按权限点隐藏按钮仅改善体验。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  createMasterItem,
  deleteMasterItem,
  fetchMasterList,
  fetchMasterOptions,
  setMasterStatus,
  updateMasterItem,
  type Dict,
} from '@/api'
import QuickCreateDialog from '@/components/QuickCreateDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { fmtMoney } from '@/utils/format'
import type { ExtraFilter, MasterColumn, MasterField } from '@/types/master'

const props = withDefaults(defineProps<{
  title: string
  subtitle?: string
  api: string
  // permView 已移除（T4-3）：查看权限由路由 meta.perm 强制校验（见 router/index.ts），
  // 本组件从未消费该 prop —— 属冗余死代码，留着会让人误以为前端另有一道防线。
  permEdit: string
  columns: MasterColumn[]
  fields: MasterField[]
  /** 状态字段口径：status（enabled/disabled 字符串）或 bool（enabled 布尔） */
  statusMode?: 'status' | 'bool'
  /** 额外筛选字段（如物料的 product_type_id） */
  extraFilters?: ExtraFilter[]
  keywordPlaceholder?: string
}>(), { statusMode: 'status', extraFilters: () => [], subtitle: '' })

const auth = useAuthStore()
const canEdit = computed(() => auth.hasPerm(props.permEdit))

const rows = ref<Dict[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const query = reactive<Dict>({ keyword: '', status: '', include_disabled: true })
const optionCache = reactive<Record<string, Dict[]>>({})

const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const form = reactive<Dict>({})

// ---------------- V2.1（N14/N15）：商品类型树 + 主数据快速新增 ----------------
const typeTree = ref<Dict[]>([])
const quickRef = ref<InstanceType<typeof QuickCreateDialog> | null>(null)
const quickKind = ref<'product' | 'product-type' | 'uom'>('product')

/** 商品类型树（`/master/product-types` 已返回现成 tree 结构） */
async function ensureTypeTree(force = false) {
  if (typeTree.value.length && !force) return
  try {
    const res: Dict = await fetchMasterList('/product-types')
    typeTree.value = (res.tree ?? res.items ?? []) as Dict[]
  } catch {
    typeTree.value = []
  }
}

function openQuick(kind: 'product' | 'product-type' | 'uom') {
  quickKind.value = kind
  quickRef.value?.open()
}

/** 快建成功 → 回填到当前表单对应字段，并保持下拉缓存同步 */
async function onQuickCreated(item: Dict) {
  if (!item) return
  if (quickKind.value === 'uom') {
    form.uom_id = item.id
    optionCache.uom = [...(optionCache.uom || []), item]
  } else if (quickKind.value === 'product-type') {
    form.product_type_id = item.id
    await ensureTypeTree(true)
  } else {
    form.product_id = item.id
  }
}

function isEnabled(row: Dict): boolean {
  return props.statusMode === 'bool' ? !!row.enabled : row.status === 'enabled'
}

function statusText(row: Dict): string {
  return isEnabled(row) ? '启用' : '停用'
}

async function loadOptions() {
  const kinds = new Set<string>()
  for (const f of props.fields) if (f.type === 'options' && f.optionKind) kinds.add(f.optionKind)
  for (const f of props.extraFilters) kinds.add(f.optionKind)
  for (const kind of kinds) {
    try {
      optionCache[kind] = await fetchMasterOptions(kind)
    } catch {
      optionCache[kind] = []
    }
  }
}

async function load() {
  loading.value = true
  try {
    const params: Dict = {
      keyword: query.keyword || undefined,
      page: page.value,
      page_size: pageSize.value,
    }
    if (props.statusMode === 'status') {
      if (query.status) params.status = query.status
    } else {
      params.include_disabled = query.include_disabled
    }
    for (const f of props.extraFilters) {
      if (query[f.prop]) params[f.prop] = query[f.prop]
    }
    const data = await fetchMasterList(props.api, params)
    rows.value = data.items ?? []
    total.value = data.total ?? rows.value.length
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function resetQuery() {
  query.keyword = ''
  query.status = ''
  query.include_disabled = true
  for (const f of props.extraFilters) query[f.prop] = ''
  page.value = 1
  load()
}

function defaultOf(field: MasterField) {
  if (field.type === 'switch') return true
  if (field.type === 'number') return 0
  return ''
}

function openNew() {
  editingId.value = null
  for (const key of Object.keys(form)) delete form[key]
  for (const f of props.fields) form[f.prop] = defaultOf(f)
  dialogVisible.value = true
}

function openEdit(row: Dict) {
  editingId.value = row.id
  for (const key of Object.keys(form)) delete form[key]
  for (const f of props.fields) form[f.prop] = row[f.prop] ?? defaultOf(f)
  dialogVisible.value = true
}

async function save() {
  for (const f of props.fields) {
    if (f.required && (form[f.prop] === '' || form[f.prop] === null || form[f.prop] === undefined)) {
      ElMessage.warning(`请填写「${f.label}」`)
      return
    }
  }
  saving.value = true
  try {
    const payload: Dict = {}
    for (const f of props.fields) payload[f.prop] = form[f.prop]
    if (editingId.value) {
      const updated = await updateMasterItem(props.api, editingId.value, payload)
      ElMessage.success(`已保存「${updated.name ?? updated.code}」`)
    } else {
      const created = await createMasterItem(props.api, payload)
      ElMessage.success(`已新增「${created.name ?? created.code}」`)
    }
    dialogVisible.value = false
    await load()
  } catch {
    // 拦截器已提示
  } finally {
    saving.value = false
  }
}

async function toggleStatus(row: Dict) {
  const next = !isEnabled(row)
  try {
    await ElMessageBox.confirm(
      `确定要${next ? '启用' : '停用'}「${row.name}」吗？停用后不影响历史数据与单据展示。`,
      '提示', { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await setMasterStatus(props.api, row.id, next)
  ElMessage.success(next ? '已启用' : '已停用')
  await load()
}

async function remove(row: Dict) {
  try {
    await ElMessageBox.confirm(
      `确定要删除「${row.name}」吗？若已被合同或单据引用，系统会提示改为停用。`,
      '删除确认', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteMasterItem(props.api, row.id)
    ElMessage.success('已删除')
  } catch {
    // 422 提示"已被引用，请改为停用"由拦截器展示
  }
  await load()
}

// fmtMoney 统一走 @/utils/format（T1-3）

onMounted(async () => {
  await loadOptions()
  await load()
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
        <div>
          <el-button v-if="canEdit" type="primary" @click="openNew">新增</el-button>
        </div>
      </div>
    </template>

    <el-form inline class="filters">
      <el-form-item label="关键词">
        <el-input v-model="query.keyword" :placeholder="keywordPlaceholder || '名称 / 编码模糊'"
                  clearable style="width: 200px" @keyup.enter="page = 1; load()" />
      </el-form-item>
      <el-form-item v-for="f in extraFilters" :key="f.prop" :label="f.label">
        <el-select v-model="query[f.prop]" clearable filterable style="width: 180px"
                   @change="page = 1; load()">
          <el-option v-for="o in optionCache[f.optionKind] || []" :key="o.id"
                     :label="o.name" :value="o.id" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="statusMode === 'status'" label="状态">
        <el-select v-model="query.status" clearable style="width: 120px" @change="page = 1; load()">
          <el-option label="启用" value="enabled" />
          <el-option label="停用" value="disabled" />
        </el-select>
      </el-form-item>
      <el-form-item v-else label="含停用">
        <el-switch v-model="query.include_disabled" @change="page = 1; load()" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="page = 1; load()">查询</el-button>
        <el-button @click="resetQuery">重置</el-button>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="rows" border stripe size="small">
      <el-table-column type="index" label="#" width="52" />
      <el-table-column v-for="c in columns" :key="c.prop" :prop="c.prop" :label="c.label"
                       :width="c.width" :min-width="c.minWidth || 120" show-overflow-tooltip>
        <template #default="{ row }">
          <el-tag v-if="c.kind === 'status'" :type="isEnabled(row) ? 'success' : 'info'" size="small">
            {{ statusText(row) }}
          </el-tag>
          <el-tag v-else-if="c.kind === 'bool'" :type="row[c.prop] ? 'success' : 'info'" size="small">
            {{ row[c.prop] ? '是' : '否' }}
          </el-tag>
          <span v-else-if="c.kind === 'money'">{{ fmtMoney(row[c.prop]) }}</span>
          <el-tag v-else-if="c.kind === 'tag'" size="small">{{ row[c.prop] || '—' }}</el-tag>
          <span v-else>{{ row[c.prop] === null || row[c.prop] === undefined || row[c.prop] === '' ? '—' : row[c.prop] }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openEdit(row)">
            {{ canEdit ? '编辑' : '查看' }}
          </el-button>
          <el-button v-if="canEdit" link :type="isEnabled(row) ? 'warning' : 'success'" size="small"
                     @click="toggleStatus(row)">
            {{ isEnabled(row) ? '停用' : '启用' }}
          </el-button>
          <el-button v-if="canEdit" link type="danger" size="small" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>暂无数据</template>
    </el-table>

    <!-- T4-1b：补 sizes（原先无法改每页条数）与 @size-change（缺它会导致改条数不生效） -->
    <el-pagination class="pager" background layout="total, prev, pager, next, sizes"
                   :total="total" :current-page="page" :page-size="pageSize"
                   :page-sizes="[10, 20, 50, 100]"
                   @current-change="(p: number) => { page = p; load() }"
                   @size-change="(s: number) => { pageSize = s; page = 1; load() }" />

    <el-dialog v-model="dialogVisible" :title="editingId ? `编辑${title}` : `新增${title}`" width="min(620px, 92vw)">
      <el-form label-width="110px">
        <el-row :gutter="12">
          <el-col v-for="f in fields" :key="f.prop" :span="f.span || 12">
            <el-form-item :label="f.label" :required="f.required">
              <el-input v-if="!f.type || f.type === 'input'" v-model="form[f.prop]"
                        :placeholder="f.placeholder" />
              <el-input v-else-if="f.type === 'textarea'" v-model="form[f.prop]" type="textarea" :rows="2" />
              <el-input-number v-else-if="f.type === 'number'" v-model="form[f.prop]"
                               :precision="f.precision" :min="f.min" :max="f.max" :step="f.step || 1"
                               :controls="false" style="width: 100%" />
              <el-switch v-else-if="f.type === 'switch'" v-model="form[f.prop]" />
              <el-select v-else-if="f.type === 'select'" v-model="form[f.prop]" style="width: 100%">
                <el-option v-for="o in f.options || []" :key="String(o.value)" :label="o.label"
                           :value="o.value" />
              </el-select>
              <div v-else-if="f.type === 'options'" class="quick-line">
                <el-select v-model="form[f.prop]" filterable clearable style="flex: 1"
                           :placeholder="f.placeholder || '请选择'">
                  <el-option v-for="o in optionCache[f.optionKind || ''] || []" :key="o.id"
                             :label="o.code ? `${o.name}（${o.code}）` : o.name" :value="o.id" />
                </el-select>
                <!-- V2.1（N15）：现场快建，不跳转（BR-V2.1-10 禁止丢失未保存表单） -->
                <el-button v-if="f.quickCreate" size="small" title="快速新增"
                           @click="openQuick(f.quickCreate!)">＋</el-button>
              </div>
              <!-- V2.1（N14）：商品类型树状展开选择；父节点禁用，只能选叶子（后端仍强制校验） -->
              <div v-else-if="f.type === 'tree-select'" class="quick-line">
                <el-tree-select v-model="form[f.prop]" :data="typeTree" check-strictly filterable
                                clearable :render-after-expand="false" style="flex: 1"
                                :props="{ label: 'name', value: 'id', children: 'children',
                                          disabled: (d: Dict) => !!(d.children && d.children.length) }"
                                :placeholder="f.placeholder || '请选择叶子类型'"
                                @visible-change="ensureTypeTree()" />
                <el-button v-if="f.quickCreate" size="small" title="快速新增"
                           @click="openQuick(f.quickCreate!)">＋</el-button>
              </div>
              <span v-if="f.tip" class="tip">{{ f.tip }}</span>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- V2.1：主数据快速新增（商品类型 / 计量单位 / 物料） -->
    <QuickCreateDialog ref="quickRef" :kind="quickKind" @created="onQuickCreated" />
  </el-card>
</template>

<style scoped>
.quick-line { display: flex; align-items: center; gap: 6px; width: 100%; }
.head { display: flex; align-items: center; justify-content: space-between; }
.title { font-weight: 600; font-size: var(--ctms-fs-md); }
.subtitle { margin-left: 10px; color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); }
.filters { margin-bottom: 4px; }
.pager { margin-top: var(--ctms-gap); justify-content: flex-end; }
.tip { margin-left: var(--ctms-gap-sm); color: var(--ctms-text-muted); font-size: var(--ctms-fs-xs); }
</style>
