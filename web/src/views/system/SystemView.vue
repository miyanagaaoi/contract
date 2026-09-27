<script setup lang="ts">
/**
 * 系统管理（T-V2-12 / AC-V2-38）：页签整合数据字典、系统参数、编号规则、
 * 操作日志、变更历史、备份与关于；原 `/settings` 功能全部保留。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import SettingsView from '@/views/SettingsView.vue'
import {
  createBackup,
  deleteBackup,
  downloadBackup,
  fetchAbout,
  fetchBackups,
  fetchChangeLogs,
  fetchNumberRules,
  fetchOperationLogs,
  fetchSysParams,
  saveNumberRules,
  saveSysParams,
  type Dict,
} from '@/api'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const active = ref('dict')

const canParamEdit = computed(() => auth.hasPerm('system.param.edit'))
const canBackup = computed(() => auth.hasPerm('system.backup.create'))
const canDownload = computed(() => auth.hasPerm('system.backup.download'))

// ---------------- 系统参数 ----------------
const params = ref<Dict>({})
const paramMeta = ref<Dict[]>([])
const paramSaving = ref(false)

async function loadParams() {
  const data = await fetchSysParams()
  params.value = data.params
  paramMeta.value = data.meta
}

async function saveParams() {
  paramSaving.value = true
  try {
    const data = await saveSysParams(params.value)
    params.value = data.params
    ElMessage.success('系统参数已保存')
  } finally {
    paramSaving.value = false
  }
}

// ---------------- 编号规则 ----------------
const rules = ref<Dict>({})
const ruleLabels = ref<Dict>({})
const rulePreviews = ref<Dict>({})
const ruleSaving = ref(false)

async function loadRules() {
  const data = await fetchNumberRules()
  rules.value = data.rules
  ruleLabels.value = data.labels
  rulePreviews.value = data.previews
}

async function saveRules() {
  ruleSaving.value = true
  try {
    await saveNumberRules(rules.value)
    ElMessage.success('编号规则已保存')
    await loadRules()
  } finally {
    ruleSaving.value = false
  }
}

// ---------------- 操作日志 ----------------
const logs = ref<Dict[]>([])
const logTotal = ref(0)
const logPage = ref(1)
const logPageSize = ref(20)
const logLoading = ref(false)
const logQuery = reactive<Dict>({ keyword: '', module: '', action: '', date_from: '', date_to: '' })
const logOptions = reactive<Dict>({ modules: [], actions: [] })

async function loadLogs() {
  logLoading.value = true
  try {
    const data = await fetchOperationLogs({
      keyword: logQuery.keyword || undefined, module: logQuery.module || undefined,
      action: logQuery.action || undefined,
      date_from: logQuery.date_from || undefined, date_to: logQuery.date_to || undefined,
      page: logPage.value, page_size: logPageSize.value,
    })
    logs.value = data.items
    logTotal.value = data.total
    logOptions.modules = data.modules
    logOptions.actions = data.actions
  } finally {
    logLoading.value = false
  }
}

function resetLogQuery() {
  Object.assign(logQuery, { keyword: '', module: '', action: '', date_from: '', date_to: '' })
  logPage.value = 1
  loadLogs()
}

// ---------------- 变更历史 ----------------
const changes = ref<Dict[]>([])
const changeTotal = ref(0)
const changePage = ref(1)
const changePageSize = ref(20)
const changeLoading = ref(false)
const changeQuery = reactive<Dict>({ keyword: '', field_name: '', date_from: '', date_to: '' })
const changeFields = ref<string[]>([])

async function loadChanges() {
  changeLoading.value = true
  try {
    const data = await fetchChangeLogs({
      keyword: changeQuery.keyword || undefined,
      field_name: changeQuery.field_name || undefined,
      date_from: changeQuery.date_from || undefined,
      date_to: changeQuery.date_to || undefined,
      page: changePage.value, page_size: changePageSize.value,
    })
    changes.value = data.items
    changeTotal.value = data.total
    changeFields.value = data.fields
  } finally {
    changeLoading.value = false
  }
}

function resetChangeQuery() {
  Object.assign(changeQuery, { keyword: '', field_name: '', date_from: '', date_to: '' })
  changePage.value = 1
  loadChanges()
}

// ---------------- 备份 ----------------
const backups = ref<Dict[]>([])
const backupLoading = ref(false)

async function loadBackups() {
  backups.value = await fetchBackups()
}

async function doBackup() {
  backupLoading.value = true
  try {
    const info = await createBackup()
    ElMessage.success(`备份已生成：${info.name}`)
    await loadBackups()
  } finally {
    backupLoading.value = false
  }
}

async function doDownload(name: string) {
  await downloadBackup(name)
}

async function doDeleteBackup(name: string) {
  try {
    await ElMessageBox.confirm(`确定要删除备份「${name}」吗？`, '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
  } catch {
    return
  }
  await deleteBackup(name)
  ElMessage.success('已删除')
  await loadBackups()
}

function fmtSize(bytes: number) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let idx = 0
  while (value >= 1024 && idx < units.length - 1) { value /= 1024; idx += 1 }
  return `${value.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`
}

// ---------------- 关于 ----------------
const about = ref<Dict | null>(null)

async function loadAbout() {
  about.value = await fetchAbout()
}

const COUNT_LABELS: Dict = {
  contracts: '合同', contracts_deleted: '已停用合同', tags: '标签', attachments: '附件',
  change_logs: '变更历史', operation_logs: '操作日志', users: '账号',
  customers: '客户', suppliers: '供应商', products: '物料',
}

async function onTabChange(name: string) {
  if (name === 'logs') await loadLogs()
  else if (name === 'changes') await loadChanges()
  else if (name === 'backup') await loadBackups()
  else if (name === 'about') await loadAbout()
}

onMounted(async () => {
  await Promise.all([loadParams(), loadRules()])
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <span class="title">系统管理</span>
      <span class="subtitle">字典 / 参数 / 编号 / 日志 / 变更历史 / 备份 / 关于</span>
    </template>

    <el-tabs v-model="active" @tab-change="onTabChange">
      <!-- 数据字典：保留 V1.0 `系统设置` 页全部能力 -->
      <el-tab-pane label="数据字典" name="dict">
        <SettingsView />
      </el-tab-pane>

      <el-tab-pane label="系统参数" name="params">
        <el-form label-width="200px" class="narrow">
          <el-form-item v-for="m in paramMeta" :key="m.key" :label="m.label">
            <el-switch v-if="m.type === 'bool'" v-model="params[m.key]" :disabled="!canParamEdit" />
            <el-input-number v-else v-model="params[m.key]" :min="m.min" :max="m.max"
                             :controls="false" :disabled="!canParamEdit" style="width: 160px" />
            <span class="tip">{{ m.note }}</span>
          </el-form-item>
          <el-form-item v-if="canParamEdit">
            <el-button type="primary" :loading="paramSaving" @click="saveParams">保存参数</el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <el-tab-pane label="编号规则" name="rules">
        <el-table :data="Object.keys(rules)" border stripe size="small">
          <el-table-column label="单据/档案" min-width="150">
            <template #default="{ row }">{{ ruleLabels[row] || row }}</template>
          </el-table-column>
          <el-table-column label="前缀" width="140">
            <template #default="{ row }">
              <el-input v-model="rules[row].prefix" size="small" maxlength="4" :disabled="!canParamEdit" />
            </template>
          </el-table-column>
          <el-table-column label="序号长度" width="140">
            <template #default="{ row }">
              <el-input-number v-model="rules[row].seq_len" :min="3" :max="8" :controls="false"
                               size="small" :disabled="!canParamEdit" style="width: 100%" />
            </template>
          </el-table-column>
          <el-table-column label="重置策略" width="110">
            <template #default="{ row }">
              {{ rules[row].reset === 'month' ? '按月' : '不重置' }}
            </template>
          </el-table-column>
          <el-table-column label="下一个编号" min-width="160">
            <template #default="{ row }">
              <span v-if="rulePreviews[row]">{{ rulePreviews[row] }}</span>
              <span v-else class="gray">该类单据尚未开放（M2/M3）</span>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="canParamEdit" class="mt12">
          <el-button type="primary" :loading="ruleSaving" @click="saveRules">保存编号规则</el-button>
        </div>
      </el-tab-pane>

      <el-tab-pane label="操作日志" name="logs">
        <el-form inline>
          <el-form-item label="关键词">
            <el-input v-model="logQuery.keyword" placeholder="单号 / 操作人 / 详情" clearable
                      style="width: 180px" @keyup.enter="logPage = 1; loadLogs()" />
          </el-form-item>
          <el-form-item label="模块">
            <el-select v-model="logQuery.module" clearable style="width: 130px">
              <el-option v-for="m in logOptions.modules" :key="m" :label="m" :value="m" />
            </el-select>
          </el-form-item>
          <el-form-item label="动作">
            <el-select v-model="logQuery.action" clearable style="width: 140px">
              <el-option v-for="a in logOptions.actions" :key="a" :label="a" :value="a" />
            </el-select>
          </el-form-item>
          <el-form-item label="时间">
            <el-date-picker v-model="logQuery.date_from" type="date" value-format="YYYY-MM-DD"
                            placeholder="起" style="width: 140px" />
            <span class="sep">~</span>
            <el-date-picker v-model="logQuery.date_to" type="date" value-format="YYYY-MM-DD"
                            placeholder="止" style="width: 140px" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="logPage = 1; loadLogs()">查询</el-button>
            <el-button @click="resetLogQuery">重置</el-button>
          </el-form-item>
        </el-form>

        <el-table v-loading="logLoading" :data="logs" border stripe size="small">
          <el-table-column prop="created_at" label="时间" width="160" />
          <el-table-column label="操作人" width="120">
            <template #default="{ row }">{{ row.real_name || row.username || '—' }}</template>
          </el-table-column>
          <el-table-column prop="module" label="模块" width="100" />
          <el-table-column prop="action" label="动作" width="120" />
          <el-table-column prop="object_no" label="对象单号" min-width="150" show-overflow-tooltip />
          <el-table-column label="结果" width="80">
            <template #default="{ row }">
              <el-tag :type="row.result === 'success' ? 'success' : 'danger'" size="small">
                {{ row.result === 'success' ? '成功' : '失败' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="detail" label="详情" min-width="200" show-overflow-tooltip />
          <el-table-column prop="ip" label="IP" width="130" />
        </el-table>
        <el-pagination v-if="logTotal > logPageSize" class="pager" background
                       layout="total, prev, pager, next, sizes"
                       :total="logTotal" :current-page="logPage" :page-size="logPageSize"
                       :page-sizes="[10, 20, 50, 100]"
                       @current-change="(p: number) => { logPage = p; loadLogs() }"
                       @size-change="(s: number) => { logPageSize = s; logPage = 1; loadLogs() }" />
      </el-tab-pane>

      <el-tab-pane label="变更历史" name="changes">
        <el-form inline>
          <el-form-item label="关键词">
            <el-input v-model="changeQuery.keyword" placeholder="合同编号 / 名称 / 字段 / 操作人"
                      clearable style="width: 220px" @keyup.enter="changePage = 1; loadChanges()" />
          </el-form-item>
          <el-form-item label="字段">
            <el-select v-model="changeQuery.field_name" clearable filterable style="width: 160px">
              <el-option v-for="f in changeFields" :key="f" :label="f" :value="f" />
            </el-select>
          </el-form-item>
          <el-form-item label="时间">
            <el-date-picker v-model="changeQuery.date_from" type="date" value-format="YYYY-MM-DD"
                            placeholder="起" style="width: 140px" />
            <span class="sep">~</span>
            <el-date-picker v-model="changeQuery.date_to" type="date" value-format="YYYY-MM-DD"
                            placeholder="止" style="width: 140px" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="changePage = 1; loadChanges()">查询</el-button>
            <el-button @click="resetChangeQuery">重置</el-button>
          </el-form-item>
        </el-form>

        <el-table v-loading="changeLoading" :data="changes" border stripe size="small">
          <el-table-column prop="created_at" label="时间" width="160" />
          <el-table-column prop="contract_no" label="合同编号" width="150" />
          <el-table-column prop="contract_name" label="合同名称" min-width="160" show-overflow-tooltip />
          <el-table-column prop="field_name" label="字段" width="120" />
          <el-table-column prop="old_value" label="旧值" min-width="120" show-overflow-tooltip />
          <el-table-column prop="new_value" label="新值" min-width="120" show-overflow-tooltip />
          <el-table-column label="操作人" width="110">
            <template #default="{ row }">{{ row.operator_name || '—' }}</template>
          </el-table-column>
          <el-table-column label="来源" width="80">
            <template #default="{ row }">{{ row.source === 'auto' ? '系统' : '手工' }}</template>
          </el-table-column>
          <el-table-column prop="note" label="备注" min-width="140" show-overflow-tooltip />
        </el-table>
        <el-pagination v-if="changeTotal > changePageSize" class="pager" background
                       layout="total, prev, pager, next, sizes" :total="changeTotal"
                       :current-page="changePage" :page-size="changePageSize"
                       :page-sizes="[10, 20, 50, 100]"
                       @current-change="(p: number) => { changePage = p; loadChanges() }"
                       @size-change="(s: number) => { changePageSize = s; changePage = 1; loadChanges() }" />
      </el-tab-pane>

      <el-tab-pane label="备份" name="backup">
        <el-alert type="info" :closable="false" show-icon class="mb12"
                  title="备份内容：SQLite 数据文件在线快照 + uploads 附件目录。解压后覆盖同名文件即可还原。" />
        <div class="mb12">
          <el-button v-if="canBackup" type="primary" :loading="backupLoading" @click="doBackup">生成备份</el-button>
          <el-button @click="loadBackups">刷新列表</el-button>
        </div>
        <el-table :data="backups" border stripe size="small">
          <el-table-column prop="name" label="备份文件" min-width="260" />
          <el-table-column label="大小" width="110">
            <template #default="{ row }">{{ fmtSize(row.size_bytes) }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="生成时间" width="180" />
          <el-table-column label="操作" width="170">
            <template #default="{ row }">
              <el-button v-if="canDownload" link type="primary" size="small"
                         @click="doDownload(row.name)">下载</el-button>
              <el-button v-if="canBackup" link type="danger" size="small"
                         @click="doDeleteBackup(row.name)">删除</el-button>
            </template>
          </el-table-column>
          <template #empty>暂无备份</template>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="关于" name="about">
        <el-descriptions v-if="about" :column="2" border>
          <el-descriptions-item label="应用">{{ about.app }}</el-descriptions-item>
          <el-descriptions-item label="版本">{{ about.version }}</el-descriptions-item>
          <el-descriptions-item label="服务器时间">{{ about.server_time }}</el-descriptions-item>
          <el-descriptions-item label="认证开关">
            {{ about.auth_enabled ? '已开启' : '已关闭（本地调试）' }}
          </el-descriptions-item>
          <el-descriptions-item label="数据库类型">{{ about.database.kind }}</el-descriptions-item>
          <el-descriptions-item label="数据库位置">{{ about.database.file }}</el-descriptions-item>
          <el-descriptions-item label="权限点数量">{{ about.permission_count }}</el-descriptions-item>
          <el-descriptions-item label="数据概览">
            <span v-for="(label, key) in COUNT_LABELS" :key="key" class="count">
              {{ label }} {{ about.counts[key] ?? 0 }}
            </span>
          </el-descriptions-item>
        </el-descriptions>
      </el-tab-pane>
    </el-tabs>
  </el-card>
</template>

<style scoped>
.title { font-weight: 600; font-size: var(--ctms-fs-md); }
.subtitle { margin-left: 10px; color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); }
.narrow { max-width: 720px; }
.tip { margin-left: 10px; color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); }
.mt12 { margin-top: var(--ctms-gap); }
.mb12 { margin-bottom: var(--ctms-gap); }
.pager { margin-top: var(--ctms-gap); justify-content: flex-end; }
.sep { margin: 0 6px; color: var(--ctms-text-muted); }
.gray { color: var(--ctms-text-muted); }
.count { margin-right: 12px; }
</style>
