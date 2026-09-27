<script setup lang="ts">
/** 角色管理（T-V2-04）：角色 CRUD、权限树勾选、数据范围；内置角色不可删除。 */
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { http, type Dict } from '@/api'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canEdit = computed(() => auth.hasPerm('master.role.edit'))

const rows = ref<Dict[]>([])
const total = ref(0)
const loading = ref(false)
const keyword = ref('')
const includeDisabled = ref(true)
const dataScopes = ref<Dict[]>([])
const permTree = ref<Dict[]>([])

const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const form = reactive<Dict>({ code: '', name: '', data_scope: 'SELF', remark: '', enabled: true })
const treeRef = ref()
const checkedCodes = ref<string[]>([])

function scopeLabel(code: string) {
  return dataScopes.value.find((s) => s.code === code)?.label || code
}

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/system/roles', {
      params: { keyword: keyword.value || undefined, include_disabled: includeDisabled.value },
    })
    rows.value = data.items
    total.value = data.total
    dataScopes.value = data.data_scopes
  } finally {
    loading.value = false
  }
}

async function loadPermTree() {
  if (permTree.value.length) return
  const { data } = await http.get('/system/permissions')
  // 统一节点形状：模块分组 + 叶子权限点（叶子 code 即权限点代码）
  permTree.value = (data.tree || []).map((group: Dict) => ({
    code: `module:${group.module}`,
    label: group.label,
    children: (group.perms || []).map((p: Dict) => ({
      code: p.code, label: `${p.name}${p.type === 'menu' ? '（菜单）' : ''}`,
    })),
  }))
  if (!dataScopes.value.length) dataScopes.value = data.data_scopes
}

function setChecked(codes: string[]) {
  const tree = treeRef.value
  if (!tree) return
  const leafCodes = new Set<string>()
  for (const group of permTree.value) for (const p of group.children || []) leafCodes.add(p.code)
  tree.setCheckedKeys(codes.filter((c) => leafCodes.has(c)))
}

async function openNew() {
  editingId.value = null
  Object.assign(form, { code: '', name: '', data_scope: 'SELF', remark: '', enabled: true })
  checkedCodes.value = []
  dialogVisible.value = true
  await loadPermTree()
  await nextTick()
  setChecked([])
}

async function openEdit(row: Dict) {
  editingId.value = row.id
  Object.assign(form, {
    code: row.code, name: row.name, data_scope: row.data_scope,
    remark: row.remark || '', enabled: row.enabled,
  })
  checkedCodes.value = row.perms || []
  dialogVisible.value = true
  await loadPermTree()
  await nextTick()
  setChecked(checkedCodes.value)
}

async function save() {
  if (!form.name) return ElMessage.warning('请填写角色名称')
  if (!editingId.value && !form.code) return ElMessage.warning('请填写角色编码')
  const tree = treeRef.value
  const perms: string[] = tree ? [...tree.getCheckedKeys(), ...tree.getHalfCheckedKeys()] : []
  saving.value = true
  try {
    if (editingId.value) {
      await http.put(`/system/roles/${editingId.value}`, {
        name: form.name, data_scope: form.data_scope, remark: form.remark, perms,
      })
      ElMessage.success('角色已保存')
    } else {
      await http.post('/system/roles', {
        code: form.code, name: form.name, data_scope: form.data_scope,
        remark: form.remark, perms,
      })
      ElMessage.success('角色已创建')
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
  const next = !row.enabled
  try {
    await ElMessageBox.confirm(`确定要${next ? '启用' : '停用'}角色「${row.name}」吗？停用后其账号将失去对应权限。`,
      '提示', { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' })
  } catch {
    return
  }
  try {
    await http.put(`/system/roles/${row.id}/status`, { enabled: next })
    ElMessage.success(next ? '已启用' : '已停用')
  } catch {
    // 内置角色不可停用等提示
  }
  await load()
}

async function remove(row: Dict) {
  try {
    await ElMessageBox.confirm(`确定要删除角色「${row.name}」吗？`, '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
  } catch {
    return
  }
  try {
    await http.delete(`/system/roles/${row.id}`)
    ElMessage.success('已删除')
  } catch {
    // 内置角色/仍有账号
  }
  await load()
}

onMounted(async () => {
  await load()
  await loadPermTree()
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="head">
        <div>
          <span class="title">角色管理</span>
          <span class="subtitle">权限点取并集、数据范围取最宽；内置角色不可删除</span>
        </div>
        <el-button v-if="canEdit" type="primary" @click="openNew">新增角色</el-button>
      </div>
    </template>

    <el-form inline>
      <el-form-item label="关键词">
        <el-input v-model="keyword" placeholder="角色名称 / 编码" clearable style="width: 200px"
                  @keyup.enter="load" />
      </el-form-item>
      <el-form-item label="含停用">
        <el-switch v-model="includeDisabled" @change="load" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="load">查询</el-button>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="rows" border stripe size="small">
      <el-table-column prop="code" label="编码" width="150" />
      <el-table-column prop="name" label="角色名称" min-width="140" />
      <el-table-column label="数据范围" width="110">
        <template #default="{ row }">{{ scopeLabel(row.data_scope) }}</template>
      </el-table-column>
      <el-table-column prop="perm_count" label="权限点" width="90" />
      <el-table-column prop="user_count" label="账号数" width="90" />
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag :type="row.builtin ? 'warning' : 'info'" size="small">
            {{ row.builtin ? '内置' : '自定义' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
            {{ row.enabled ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="remark" label="说明" min-width="160" show-overflow-tooltip />
      <el-table-column v-if="canEdit" label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
          <el-button link :type="row.enabled ? 'warning' : 'success'" size="small"
                     @click="toggleStatus(row)">{{ row.enabled ? '停用' : '启用' }}</el-button>
          <el-button v-if="!row.builtin" link type="danger" size="small" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑角色' : '新增角色'" width="min(720px, 92vw)">
      <el-form label-width="90px">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="角色编码" required>
              <el-input v-model="form.code" :disabled="!!editingId" placeholder="字母开头，如 purchase_mgr" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="角色名称" required><el-input v-model="form.name" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="数据范围">
              <el-select v-model="form.data_scope" style="width: 100%">
                <el-option v-for="s in dataScopes" :key="s.code" :label="s.label" :value="s.code" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="说明"><el-input v-model="form.remark" /></el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="权限点">
          <div class="perm-box">
            <el-tree ref="treeRef" :data="permTree" show-checkbox node-key="code"
                     :props="{ label: 'label', children: 'children' }" default-expand-all />
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; }
.title { font-weight: 600; font-size: var(--ctms-fs-md); }
.subtitle { margin-left: 10px; color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); }
.perm-box { width: 100%; max-height: 320px; overflow: auto; border: 1px solid #e4e7ed; border-radius: 4px; padding: 6px 10px; }
</style>
