<script setup lang="ts">
/** 账号管理（T-V2-05 / AC-V2-08）：新增、编辑、角色分配、重置密码、停用启用。 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { http, type Dict } from '@/api'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canEdit = computed(() => auth.hasPerm('master.user.edit'))
const canReset = computed(() => auth.hasPerm('master.user.resetpwd'))

const rows = ref<Dict[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)

const query = reactive<Dict>({ keyword: '', org_id: '', role_id: '', status: '' })
const roles = ref<Dict[]>([])
const orgs = ref<Dict[]>([])
const dataScopes = ref<Dict[]>([])

function scopeLabel(role: Dict): string {
  const found = dataScopes.value.find((s) => s.code === role.data_scope)
  return found?.label || role.data_scope || ''
}

const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const form = reactive<Dict>({
  username: '', real_name: '', password: '', org_id: '', phone: '', email: '', remark: '',
  role_ids: [] as number[],
})

const pwdVisible = ref(false)
const pwdTarget = ref<Dict | null>(null)
const newPassword = ref('')

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/system/users', {
      params: {
        keyword: query.keyword || undefined,
        org_id: query.org_id || undefined,
        role_id: query.role_id || undefined,
        status: query.status || undefined,
        page: page.value,
        page_size: pageSize.value,
      },
    })
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

async function loadRefs() {
  const [r, o] = await Promise.all([
    http.get('/system/roles', { params: { include_disabled: true } }),
    http.get('/system/org-units', { params: { include_disabled: true } }),
  ])
  roles.value = r.data.items
  orgs.value = o.data.items
  dataScopes.value = r.data.data_scopes || []
}

function resetQuery() {
  Object.assign(query, { keyword: '', org_id: '', role_id: '', status: '' })
  page.value = 1
  load()
}

function openNew() {
  editingId.value = null
  Object.assign(form, {
    username: '', real_name: '', password: '', org_id: '', phone: '', email: '', remark: '',
    role_ids: [],
  })
  dialogVisible.value = true
}

function openEdit(row: Dict) {
  editingId.value = row.id
  Object.assign(form, {
    username: row.username, real_name: row.real_name, password: '',
    org_id: row.org_id || '', phone: row.phone || '', email: row.email || '',
    remark: row.remark || '', role_ids: (row.roles || []).map((r: Dict) => r.id),
  })
  dialogVisible.value = true
}

async function save() {
  if (!form.real_name) return ElMessage.warning('请填写真实姓名')
  if (!editingId.value && !form.username) return ElMessage.warning('请填写登录名')
  if (!editingId.value && !form.password) return ElMessage.warning('请填写初始密码')
  saving.value = true
  try {
    if (editingId.value) {
      await http.put(`/system/users/${editingId.value}`, {
        real_name: form.real_name, org_id: form.org_id || null, phone: form.phone,
        email: form.email, remark: form.remark, role_ids: form.role_ids,
      })
      ElMessage.success('账号已保存')
    } else {
      await http.post('/system/users', {
        username: form.username, real_name: form.real_name, password: form.password,
        org_id: form.org_id || null, phone: form.phone, email: form.email,
        remark: form.remark, role_ids: form.role_ids,
      })
      ElMessage.success('账号已创建；首次登录需修改密码')
    }
    dialogVisible.value = false
    await load()
  } catch {
    // 拦截器已提示（密码强度/登录名重复等）
  } finally {
    saving.value = false
  }
}

async function toggleStatus(row: Dict) {
  const next = row.status !== 'enabled'
  try {
    await ElMessageBox.confirm(
      `确定要${next ? '启用' : '停用'}账号「${row.real_name || row.username}」吗？停用后该账号的登录令牌立即失效。`,
      '提示', { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' })
  } catch {
    return
  }
  try {
    await http.put(`/system/users/${row.id}/status`, { enabled: next })
    ElMessage.success(next ? '已启用' : '已停用')
  } catch {
    // 不可停用自己/最后一个超管
  }
  await load()
}

function openReset(row: Dict) {
  pwdTarget.value = row
  newPassword.value = ''
  pwdVisible.value = true
}

async function doReset() {
  if (!pwdTarget.value) return
  if (!newPassword.value) return ElMessage.warning('请输入新密码')
  try {
    await http.post(`/system/users/${pwdTarget.value.id}/reset-password`, {
      new_password: newPassword.value,
    })
    ElMessage.success('已重置；该账号下次登录需修改密码')
    pwdVisible.value = false
  } catch {
    // 强度校验提示
  }
}

onMounted(async () => {
  await loadRefs()
  await load()
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="head">
        <div>
          <span class="title">账号管理</span>
          <span class="subtitle">登录名创建后不可修改；新账号与重置密码后首次登录强制改密</span>
        </div>
        <el-button v-if="canEdit" type="primary" @click="openNew">新增账号</el-button>
      </div>
    </template>

    <el-form inline>
      <el-form-item label="关键词">
        <el-input v-model="query.keyword" placeholder="登录名 / 姓名" clearable style="width: 180px"
                  @keyup.enter="page = 1; load()" />
      </el-form-item>
      <el-form-item label="组织">
        <el-select v-model="query.org_id" clearable filterable style="width: 160px">
          <el-option v-for="o in orgs" :key="o.id" :label="o.name" :value="o.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="角色">
        <el-select v-model="query.role_id" clearable style="width: 150px">
          <el-option v-for="r in roles" :key="r.id" :label="r.name" :value="r.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="状态">
        <el-select v-model="query.status" clearable style="width: 110px">
          <el-option label="启用" value="enabled" />
          <el-option label="停用" value="disabled" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="page = 1; load()">查询</el-button>
        <el-button @click="resetQuery">重置</el-button>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="rows" border stripe size="small">
      <el-table-column prop="username" label="登录名" width="130" />
      <el-table-column prop="real_name" label="姓名" width="110" />
      <el-table-column prop="org_name" label="组织" min-width="130">
        <template #default="{ row }">{{ row.org_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="角色" min-width="160">
        <template #default="{ row }">
          <el-tag v-for="r in row.roles" :key="r.id" size="small" class="mr4">{{ r.name }}</el-tag>
          <span v-if="!row.roles?.length" class="gray">未分配</span>
        </template>
      </el-table-column>
      <el-table-column label="超管" width="70">
        <template #default="{ row }">
          <el-tag v-if="row.is_superadmin" type="danger" size="small">是</el-tag>
          <span v-else class="gray">否</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.status === 'enabled' ? 'success' : 'info'" size="small">
            {{ row.status === 'enabled' ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="需改密" width="80">
        <template #default="{ row }">
          <el-tag v-if="row.must_change_pwd" type="warning" size="small">是</el-tag>
          <span v-else class="gray">否</span>
        </template>
      </el-table-column>
      <el-table-column prop="last_login_at" label="最后登录" width="150">
        <template #default="{ row }">{{ row.last_login_at || '—' }}</template>
      </el-table-column>
      <el-table-column v-if="canEdit || canReset" label="操作" width="210" fixed="right">
        <template #default="{ row }">
          <el-button v-if="canEdit" link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="canReset" link type="warning" size="small" @click="openReset(row)">重置密码</el-button>
          <el-button v-if="canEdit" link :type="row.status === 'enabled' ? 'info' : 'success'" size="small"
                     @click="toggleStatus(row)">
            {{ row.status === 'enabled' ? '停用' : '启用' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- T4-1b：补 sizes 与 @size-change（缺后者会导致改每页条数不重新加载） -->
    <el-pagination class="pager" background layout="total, prev, pager, next, sizes"
                   :total="total" :current-page="page" :page-size="pageSize"
                   :page-sizes="[10, 20, 50, 100]"
                   @current-change="(p: number) => { page = p; load() }"
                   @size-change="(s: number) => { pageSize = s; page = 1; load() }" />

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑账号' : '新增账号'" width="min(620px, 92vw)">
      <el-form label-width="100px">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="登录名" required>
              <el-input v-model="form.username" :disabled="!!editingId" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="真实姓名" required><el-input v-model="form.real_name" /></el-form-item>
          </el-col>
          <el-col v-if="!editingId" :span="12">
            <el-form-item label="初始密码" required>
              <el-input v-model="form.password" type="password" show-password
                        placeholder="需满足系统参数中的密码最小长度" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="所属组织">
              <el-select v-model="form.org_id" clearable filterable style="width: 100%">
                <el-option v-for="o in orgs" :key="o.id" :label="o.name" :value="o.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="手机号"><el-input v-model="form.phone" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="邮箱"><el-input v-model="form.email" /></el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="角色">
              <el-select v-model="form.role_ids" multiple filterable style="width: 100%">
                <el-option v-for="r in roles" :key="r.id" :label="`${r.name}（${scopeLabel(r)}）`" :value="r.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="2" /></el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="pwdVisible" title="重置密码" width="min(420px, 92vw)">
      <el-form label-width="90px">
        <el-form-item label="账号">
          <span>{{ pwdTarget?.real_name }}（{{ pwdTarget?.username }}）</span>
        </el-form-item>
        <el-form-item label="新密码" required>
          <el-input v-model="newPassword" type="password" show-password />
        </el-form-item>
        <div class="gray">重置后该账号下次登录必须修改密码。</div>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" @click="doReset">确定重置</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; }
.title { font-weight: 600; font-size: var(--ctms-fs-md); }
.subtitle { margin-left: 10px; color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); }
.pager { margin-top: var(--ctms-gap); justify-content: flex-end; }
.mr4 { margin-right: 4px; }
.gray { color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); }
</style>
