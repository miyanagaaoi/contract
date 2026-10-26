<script setup lang="ts">
/**
 * V2.6 发票同步向导（docs/38 §5 / 设计稿 ②）。
 *
 * 四步：选区间 → 平台登录（等待短信验证码）→ 抓取 → 完成。
 * 状态机由后端同步日志驱动：running / waiting_sms / success / failed；
 * 会话保活（1 小时）时自动跳过登录步骤，前端只展示「免登录」提示。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import {
  fetchInvoiceSyncInfo, fetchInvoiceSyncStatus, startInvoiceSync, submitInvoiceSyncSms,
} from '@/api'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void
                           (e: 'done'): void }>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

type Phase = 'setup' | 'login' | 'running' | 'done' | 'failed'
const phase = ref<Phase>('setup')
const info = ref<Record<string, any>>({})
const companies = ref<Record<string, any>[]>([])
const subjectCode = ref('')
const dateFrom = ref('')
const dateTo = ref('')
const smsCode = ref('')
const smsBusy = ref(false)
const smsRemain = ref(0)                 // 验证码等待倒计时（秒）
const result = ref<Record<string, any>>({})
const failMessage = ref('')
let pollTimer: ReturnType<typeof setTimeout> | null = null
let smsTimer: ReturnType<typeof setInterval> | null = null
let pollId = 0

function startSmsCountdown(seconds = 600) {
  stopSmsCountdown()
  smsRemain.value = seconds
  smsTimer = setInterval(() => {
    smsRemain.value = Math.max(0, smsRemain.value - 1)
    if (smsRemain.value === 0) stopSmsCountdown()
  }, 1000)
}
function stopSmsCountdown() {
  if (smsTimer) { clearInterval(smsTimer); smsTimer = null }
}
const smsRemainText = computed(() => {
  const m = Math.floor(smsRemain.value / 60)
  const s = smsRemain.value % 60
  return `${m}:${String(s).padStart(2, '0')}`
})

const stepIndex = computed(() => {
  if (phase.value === 'setup') return 0
  if (phase.value === 'login') return 1
  if (phase.value === 'running') return 2
  return 3
})
const waitingSms = computed(() => phase.value === 'login')
const currentCompany = computed(() =>
  companies.value.find((c) => c.code === subjectCode.value))

/** 无头/无图形环境（容器部署）提示：没有可见窗口，无法人工完成验证码 */
const headlessWarn = computed(() => {
  const info2 = info.value || {}
  if (!info2.headless) return ''
  const fresh = companies.value.some((c) => c.session_fresh)
  if (fresh) return ''
  return '当前为无头模式（容器/服务器部署），不会弹出浏览器窗口，无法人工完成点字/短信验证。'
    + '请先把办公机登录后的 state_<主体码>.json 复制到容器 /app/app/data/tax_session/ 复用会话'
    + '（1 小时内有效），或改用「上传发票包」/ 浏览器桥接通道。'
})

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

watch(visible, async (v) => {
  if (!v) return
  phase.value = 'setup'
  smsCode.value = ''
  result.value = {}
  failMessage.value = ''
  info.value = await fetchInvoiceSyncInfo().catch(() => ({}))
  companies.value = (info.value?.companies || []) as Record<string, any>[]
  // 默认选中：第一家「已配置凭据且会话保活中」的，否则第一家已配置的
  const fresh = companies.value.find((c) => c.session_fresh && c.configured)
  const configured = companies.value.find((c) => c.configured)
  subjectCode.value = (fresh || configured || ({} as any)).code || ''
  const to = today()
  const from = info.value?.last_at ? String(info.value.last_at).slice(0, 10) : to
  dateFrom.value = from
  dateTo.value = to
})

/** 选中公司的会话连接状态（下拉选择后展示） */
const sessionStatus = computed(() => {
  const c = companies.value.find((x) => x.code === subjectCode.value)
  if (!c) return null
  if (!c.configured) {
    return { type: 'warning' as const,
             text: `主体 ${c.code} 未配置同步凭据：请在 .env 里预充 CTMS_TAX_SYNC_${c.code}_USERNAME / _PASSWORD 后重启服务。` }
  }
  if (c.session_fresh) {
    return { type: 'success' as const,
             text: '登录会话保活中（1 小时内），本次同步免登录直接抓取。' }
  }
  return { type: 'info' as const,
           text: '会话已过期 / 未登录：发起同步后将自动登录平台，需要输入手机短信验证码。' }
})

function stopPoll() {
  if (pollTimer) { clearTimeout(pollTimer); pollTimer = null }
}

async function poll(id: number) {
  if (pollId !== id) return               // 已有更新一轮的轮询接管
  try {
    const st = await fetchInvoiceSyncStatus(id)
    if (st.status === 'waiting_sms' && phase.value !== 'login') {
      phase.value = 'login'
      startSmsCountdown()
    }
    if (st.status === 'success') {
      phase.value = 'done'
      result.value = st
      stopSmsCountdown()
      emit('done')
      stopPoll()
      return
    }
    if (st.status === 'failed') {
      phase.value = 'failed'
      failMessage.value = String(st.message || '同步失败')
      stopSmsCountdown()
      stopPoll()
      return
    }
  } catch { /* 网络抖动：继续轮询 */ }
  pollTimer = setTimeout(() => poll(id), 2000)
}

async function start() {
  if (!subjectCode.value) {
    ElMessage.warning('请选择要同步的我方公司')
    return
  }
  if (!dateFrom.value || !dateTo.value) {
    ElMessage.warning('请选择开票日期区间')
    return
  }
  try {
    const { sync_id: syncId } = await startInvoiceSync(dateFrom.value, dateTo.value,
                                                       subjectCode.value)
    pollId = syncId
    // 会话保活中后端直接进入抓取；否则先 running（登录中）再 waiting_sms
    phase.value = currentCompany.value?.session_fresh ? 'running' : 'login'
    if (phase.value === 'login' && !currentCompany.value?.session_fresh) startSmsCountdown()
    poll(syncId)
  } catch { /* 拦截器已提示 */ }
}

async function submitSms() {
  if (!smsCode.value.trim() || !pollId) return
  smsBusy.value = true
  try {
    await submitInvoiceSyncSms(pollId, smsCode.value.trim())
    phase.value = 'running'
  } catch { /* 拦截器已提示 */ } finally {
    smsBusy.value = false
  }
}

function close() {
  stopPoll()
  stopSmsCountdown()
  visible.value = false
}
</script>

<template>
  <el-dialog v-model="visible" title="同步发票" width="560px" :close-on-click-modal="false"
             @close="close">
    <el-steps :active="stepIndex" align-center finish-status="success" style="margin-bottom: 18px">
      <el-step title="选择区间" />
      <el-step title="平台登录" />
      <el-step title="抓取发票" />
      <el-step title="完成" />
    </el-steps>

    <!-- 步骤 1：选区间 + 公司 -->
    <template v-if="phase === 'setup'">
      <el-form label-width="90px" style="margin-bottom: 12px">
        <el-form-item label="我方公司">
          <!-- 选项 = 系统管理「我方公司」字典全量主体码；用主体码匹配 .env 凭据 -->
          <el-select v-model="subjectCode" style="width: 100%"
                     placeholder="选择要同步的公司（取自系统管理·我方公司）">
            <el-option v-for="c in companies" :key="c.code" :value="c.code"
                       :label="`${c.name}（${c.code}）`" :disabled="!c.configured">
              <span style="display: flex; justify-content: space-between; align-items: center">
                <span>{{ c.name }}（{{ c.code }}）</span>
                <el-tag v-if="!c.configured" type="warning" size="small">未配置凭据</el-tag>
                <el-tag v-else-if="c.session_fresh" type="success" size="small">免登录</el-tag>
                <el-tag v-else type="info" size="small">需登录</el-tag>
              </span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="开票日期">
          <el-date-picker v-model="dateFrom" type="date" value-format="YYYY-MM-DD"
                          placeholder="开始" style="width: 150px" /> ~
          <el-date-picker v-model="dateTo" type="date" value-format="YYYY-MM-DD"
                          placeholder="结束" style="width: 150px" />
        </el-form-item>
      </el-form>
      <!-- 选中后显示该公司的会话连接状态 -->
      <el-alert v-if="sessionStatus" :type="sessionStatus.type" :closable="false"
                :title="sessionStatus.text" style="margin-bottom: 12px" />
      <el-alert v-if="headlessWarn" type="warning" :closable="false"
                :title="headlessWarn" style="margin-bottom: 12px" />
      <el-alert v-if="!companies.some((c) => c.configured)" type="warning" :closable="false"
                title="尚未配置任何公司的同步凭据：请在 .env 里按 CTMS_TAX_SYNC_<主体码>_USERNAME/PASSWORD 预充后重启服务。" />
      <el-alert v-else type="info" :closable="false"
                title="仅同步「取得发票、状态正常」的进项发票；重复发票号自动跳过。各公司需分别登录。" />
    </template>

    <!-- 步骤 2：人工验证（点字/滑块/短信码都在弹出的浏览器窗口里完成） -->
    <template v-else-if="phase === 'login'">
      <el-alert type="warning" :closable="false" style="margin-bottom: 12px">
        <b>请到刚弹出的浏览器窗口里人工完成验证：</b>
        <ol style="margin: 6px 0 0 18px; line-height: 1.8">
          <li>若出现「请依次点击文字」的图片验证码 → 按提示依次点击对应文字，点「确定」；</li>
          <li>若出现短信验证码输入框 → 填写手机收到的验证码（系统检测到填了 4 位以上会自动点「登录」）；</li>
          <li>登录成功后本向导会<b>自动继续</b>抓取，无需其他操作。</li>
        </ol>
      </el-alert>
      <el-card shadow="never">
        <p>
          <span class="spinner" /> 等待人工验证完成…
          <span v-if="smsRemain > 0" class="countdown">（剩余 {{ smsRemainText }}）</span>
        </p>
        <p class="hint">
          窗口找不到？请检查任务栏是否有新的 Chrome 窗口；验证码 10 分钟内有效。
        </p>
      </el-card>
    </template>

    <!-- 步骤 3：抓取中 -->
    <template v-else-if="phase === 'running'">
      <el-card shadow="never">
        <p><span class="spinner" /> 正在抓取发票数据，请稍候…（登录成功后自动继续）</p>
      </el-card>
    </template>

    <!-- 步骤 4：完成 / 失败 -->
    <template v-else-if="phase === 'done'">
      <el-row :gutter="12">
        <el-col :span="8"><el-statistic title="拉取发票" :value="result.fetched || 0" /></el-col>
        <el-col :span="8"><el-statistic title="新增入库" :value="result.inserted || 0" /></el-col>
        <el-col :span="8"><el-statistic title="重复跳过" :value="result.skipped_duplicate || 0" /></el-col>
      </el-row>
      <el-alert type="success" :closable="false" style="margin-top: 14px"
                title="已同步发票均标记「已认证 / 未确认」，可在列表或采购单绑定弹窗中确认。会话已保活，1 小时内再次同步免登录。" />
    </template>
    <template v-else-if="phase === 'failed'">
      <el-alert type="error" :closable="false" title="同步失败">
        {{ failMessage }}
      </el-alert>
    </template>

    <template #footer>
      <template v-if="phase === 'setup'">
        <el-button @click="close">取消</el-button>
        <el-button type="primary" @click="start">开始同步</el-button>
      </template>
      <template v-else-if="phase === 'login'">
        <el-button @click="close">取消同步</el-button>
      </template>
      <template v-else-if="phase === 'done' || phase === 'failed'">
        <el-button @click="phase = 'setup'">再同步一次</el-button>
        <el-button type="primary" @click="close">完成</el-button>
      </template>
    </template>
  </el-dialog>
</template>

<style scoped>
.hint { color: var(--el-text-color-secondary); font-size: 12px; margin-top: 10px }
.countdown { color: var(--el-color-warning); font-size: 13px; font-variant-numeric: tabular-nums }
.spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--el-border-color);
           border-top-color: var(--el-color-primary); border-radius: 50%;
           animation: v2sync-spin .8s linear infinite; vertical-align: -2px; margin-right: 6px }
@keyframes v2sync-spin { to { transform: rotate(360deg) } }
</style>
