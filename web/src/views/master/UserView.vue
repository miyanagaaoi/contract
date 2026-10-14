<script setup lang="ts">
/** 账号管理（T-V2-05 / AC-V2-08）：新增、编辑、角色分配、重置密码、停用启用。 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { http, fetchUserSignatureUrl, uploadUserSignature, deleteUserSignature, type Dict } from '@/api'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canEdit = computed(() => auth.hasPerm('master.user.edit'))
const canReset = computed(() => auth.hasPerm('master.user.resetpwd'))

const rows = ref<Dict[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)

const query = reactive<Dict>({ keyword: '', org_id: '', role_id: '', status: '', awaiting_role: '' })
const roles = ref<Dict[]>([])
const orgs = ref<Dict[]>([])
const dataScopes = ref<Dict[]>([])

// ---- V2.4：飞书绑定（无 `system.feishu.view` 权限或未启用时整列不渲染，不影响既有账号管理） ----
const feishuReady = ref(false)
const feishuBindings = ref<Record<number, Dict>>({})
const canFeishu = computed(() => auth.hasPerm('system.feishu.view'))
const canFeishuEdit = computed(() => auth.hasPerm('system.feishu.edit'))

function scopeLabel(role: Dict): string {
  const found = dataScopes.value.find((s) => s.code === role.data_scope)
  return found?.label || role.data_scope || ''
}

const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
/** 正在编辑的账号是否「待分配角色」（弹窗里给一句上下文，管理员才知道为什么点进来的） */
const editingAwaitingRole = ref(false)
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
        // V2.5：只看「待分配角色」（飞书扫码自动建号的账号一开始都没有角色）
        awaiting_role: query.awaiting_role ? true : undefined,
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
  Object.assign(query, { keyword: '', org_id: '', role_id: '', status: '', awaiting_role: '' })
  page.value = 1
  load()
}

function openNew() {
  editingId.value = null
  editingAwaitingRole.value = false
  Object.assign(form, {
    username: '', real_name: '', password: '', org_id: '', phone: '', email: '', remark: '',
    role_ids: [],
  })
  dialogVisible.value = true
}

function openEdit(row: Dict) {
  editingId.value = row.id
  editingAwaitingRole.value = !!row.awaiting_role
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

// ---------------- 电子签名（预存手写签名图片，打印单据时嵌入签字位） ----------------

const sigVisible = ref(false)
const sigTarget = ref<Dict | null>(null)
const sigUrl = ref<string | null>(null)
const sigUploading = ref(false)
/** 签名按钮：超管/有账号编辑权可维护任何人，普通用户只能维护自己的（后端同口径校验） */
const canSign = (row: Dict) => auth.user ? (canEdit.value || auth.isSuperadmin || row.id === auth.user.id) : false

function openSignature(row: Dict) {
  sigTarget.value = row
  sigVisible.value = true
  void loadSignaturePreview(row)
}

async function loadSignaturePreview(row: Dict) {
  if (sigUrl.value) URL.revokeObjectURL(sigUrl.value)
  sigUrl.value = null
  // 只在列表标注「已签名」时才请求，避免无签名账号每次打开都弹 404 错误提示
  if (row.has_signature) sigUrl.value = await fetchUserSignatureUrl(Number(row.id))
}

async function onSignatureChange(file: { raw?: File }) {   // el-upload on-change：取 raw 即原 File
  const raw = file.raw
  if (!raw || !sigTarget.value) return
  sigUploading.value = true
  try {
    await uploadUserSignature(Number(sigTarget.value.id), raw)
    ElMessage.success('签名已上传；打印单据时将在签字位嵌入该图片')
    await load()      // 刷新 has_signature 列表状态
    await loadSignaturePreview({ ...sigTarget.value, has_signature: true })
  } catch {
    // 拦截器已提示（格式/大小/权限）
  } finally {
    sigUploading.value = false
  }
}

async function removeSignature() {
  if (!sigTarget.value) return
  try {
    await ElMessageBox.confirm('删除后打印单据将退回「姓名 + 手写留白」，确定删除吗？',
      '提示', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
  } catch {
    return
  }
  try {
    await deleteUserSignature(Number(sigTarget.value.id))
    ElMessage.success('签名已删除')
    await load()
    await loadSignaturePreview({ ...sigTarget.value, has_signature: false })
  } catch {
    // 拦截器已提示
  }
}

function closeSignature() {
  if (sigUrl.value) URL.revokeObjectURL(sigUrl.value)
  sigUrl.value = null
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

/**
 * 飞书绑定状态（V2.4）。
 *
 * 无权限（403）或飞书未启用时**静默降级**：不显示飞书列 —— 账号管理本身不受任何影响。
 */
async function loadFeishu() {
  try {
    const { data } = await http.get('/system/feishu/config')
    feishuReady.value = !!data.enabled
    feishuBindings.value = data.bindings || {}
  } catch {
    feishuReady.value = false
    feishuBindings.value = {}
  }
}

async function unbindFeishuOf(row: Dict) {
  try {
    await ElMessageBox.confirm(
      `确定解绑「${row.real_name || row.username}」的飞书身份吗？解绑后该账号不能再飞书免登，` +
      '需要重新绑定；换人 / 离职场景请务必解绑，否则消息会继续投递给下一位使用者。',
      '提示', { type: 'warning', confirmButtonText: '确定解绑', cancelButtonText: '取消' })
  } catch {
    return
  }
  await http.post('/system/feishu/unbind', { user_id: row.id })
  ElMessage.success('已解绑')
  await loadFeishu()
}

onMounted(async () => {
  await loadRefs()
  await load()
  await loadFeishu()
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="head">
        <div>
          <span class="title">账号管理</span>
          <span class="subtitle">登录名创建后不可修改；新账号与重置密码后首次登录强制改密；
            飞书扫码自动创建的账号默认无角色，分配角色后才可用</span>
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
      <!-- V2.5：飞书扫码自动建号的账号没有任何角色，管理员要能一键筛出来 -->
      <el-form-item label="角色分配">
        <el-select v-model="query.awaiting_role" clearable style="width: 130px"
                   placeholder="全部">
          <el-option label="待分配角色" value="1" />
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
      <el-table-column label="角色" min-width="170">
        <template #default="{ row }">
          <!-- 飞书自动建号 / 角色被停用：都能登录，但看不到任何菜单，必须让管理员一眼看到 -->
          <el-tag v-if="row.awaiting_role" type="warning" size="small">待分配角色</el-tag>
          <template v-else>
            <el-tag v-for="r in row.roles" :key="r.id" size="small" class="mr4">{{ r.name }}</el-tag>
            <span v-if="!row.roles?.length" class="gray">未分配</span>
          </template>
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
      <!-- V2.4：飞书绑定状态（未启用 / 无权限时整列不渲染） -->
      <el-table-column v-if="feishuReady && canFeishu" label="飞书" width="110">
        <template #default="{ row }">
          <el-tag v-if="feishuBindings[row.id]" type="success" size="small">
            {{ feishuBindings[row.id].display_name || '已绑定' }}
          </el-tag>
          <el-tag v-else type="info" size="small">未绑定</el-tag>
        </template>
      </el-table-column>
      <!-- 任何登录账号至少能维护自己的签名（本人/超管/账号编辑权，见 canSign） -->
      <el-table-column v-if="canEdit || canReset || (feishuReady && canFeishuEdit) || auth.user"
                       label="操作" width="340" fixed="right">
        <template #default="{ row }">
          <el-button v-if="canEdit" link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
          <!-- 待分配角色：直接把编辑弹窗拉起来（同一个保存路径，不新增接口） -->
          <el-button v-if="canEdit && row.awaiting_role" link type="warning" size="small"
                     @click="openEdit(row)">分配角色</el-button>
          <el-button v-if="canReset" link type="warning" size="small" @click="openReset(row)">重置密码</el-button>
          <!-- 电子签名：预存手写签名图片（打印入库/出库单等单据时嵌入签字位） -->
          <el-button v-if="canSign(row)" link type="primary" size="small" @click="openSignature(row)">
            签名{{ row.has_signature ? '✓' : '' }}
          </el-button>
          <el-button v-if="canEdit" link :type="row.status === 'enabled' ? 'info' : 'success'" size="small"
                     @click="toggleStatus(row)">
            {{ row.status === 'enabled' ? '停用' : '启用' }}
          </el-button>
          <el-button v-if="feishuReady && canFeishuEdit && feishuBindings[row.id]" link type="danger"
                     size="small" @click="unbindFeishuOf(row)">解绑飞书</el-button>
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
      <el-alert v-if="editingAwaitingRole" type="warning" :closable="false" show-icon class="mb12"
                title="该账号还没有任何角色"
                description="飞书扫码登录自动创建的账号不带角色：不分配角色的话，登录后只能看到「等待分配角色」页。" />
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

    <!-- 电子签名：预览当前签名 + 上传覆盖 / 删除（打印单据时嵌入签字位） -->
    <el-dialog v-model="sigVisible" title="电子签名" width="min(460px, 92vw)" @closed="closeSignature">
      <el-form label-width="90px">
        <el-form-item label="账号">
          <span>{{ sigTarget?.real_name }}（{{ sigTarget?.username }}）</span>
        </el-form-item>
        <el-form-item label="当前签名">
          <img v-if="sigUrl" :src="sigUrl" alt="签名预览" class="sig-preview" />
          <span v-else class="gray">未上传（打印单据时退回「姓名 + 手写留白」）</span>
        </el-form-item>
        <el-form-item label="上传/更换">
          <!-- auto-upload=false + on-change 手动上传：选完文件立即传，扩展名与大小由后端统一校验 -->
          <el-upload :show-file-list="false" :auto-upload="false" accept=".png,.jpg,.jpeg"
                     :on-change="onSignatureChange" :disabled="sigUploading">
            <el-button type="primary" size="small" :loading="sigUploading">
              选择图片（PNG/JPG，≤500KB）
            </el-button>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button v-if="sigUrl" type="danger" @click="removeSignature">删除签名</el-button>
        <el-button @click="sigVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; }
.title { font-weight: 600; font-size: var(--ctms-fs-md); }
.subtitle { margin-left: 10px; color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); }
.pager { margin-top: var(--ctms-gap); justify-content: flex-end; }
.mb12 { margin-bottom: var(--ctms-gap); }
.mr4 { margin-right: 4px; }
.gray { color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); }
.sig-preview { max-height: 64px; max-width: 260px; vertical-align: middle; }
</style>
