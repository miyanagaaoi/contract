<script setup lang="ts">
/**
 * 飞书授权回调页（`/feishu/callback`，V2.4）。
 *
 * ## 为什么回调落在**前端路由**而不是后端 302
 *
 * 1. 令牌统一由 `@/utils/token` 落库（唯一真源），后端 302 会让令牌出现在 URL 里，
 *    被浏览器历史、代理日志、Referer 留下；
 * 2. 失败提示、首登强制改密、redirect 回跳都能复用登录页那一套逻辑，不必两处维护。
 *
 * ## 两种模式
 *
 * - `login`（默认）：免登 —— 用授权码换本系统令牌并进入系统；
 * - `bind`：自助绑定 —— 已登录用户把自己的飞书身份绑到当前账号。
 *
 * **场景（登录/绑定）从 `state` 里读**，不依赖 sessionStorage：飞书要求 `redirect_uri`
 * 与后台登记地址完全一致，不能在 URL 上追加 `?mode=`；而 sessionStorage 是**按 origin 隔离**的，
 * 从 `localhost` 跳回内网 IP 时会丢，导致绑定被误当成登录。签进 `state` 则一定随回调带回。
 * （回跳地址仍放 sessionStorage —— 丢了只会回首页，不影响正确性。）
 */
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { bindFeishu } from '@/api'
import { useAuthStore } from '@/stores/auth'

const FEISHU_REDIRECT_KEY = 'ctms_feishu_redirect'

/** 从已签名的 `state` 读场景（第 3 段）；签名由后端校验，前端只借此选分支。 */
function modeFromState(state: string): 'login' | 'bind' {
  return state.split('.')[2] === 'bind' ? 'bind' : 'login'
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const busy = ref(true)
const error = ref('')

onMounted(async () => {
  const code = String(route.query.code || '')
  const state = String(route.query.state || '')
  const denied = String(route.query.error || '')
  const mode = modeFromState(state)
  const redirect = sessionStorage.getItem(FEISHU_REDIRECT_KEY) || '/'
  sessionStorage.removeItem(FEISHU_REDIRECT_KEY)

  if (denied) {
    error.value = '已取消飞书授权'
    busy.value = false
    return
  }
  if (!code || !state) {
    error.value = '飞书回调缺少必要参数（code/state），请重新发起'
    busy.value = false
    return
  }

  try {
    if (mode === 'bind') {
      await bindFeishu(code, state)
      ElMessage.success('飞书身份绑定成功')
      router.replace('/')
      return
    }
    const data = await auth.feishuLogin(code, state)
    if (data.auto_provisioned) {
      // 未绑定的飞书账号 → 后端自动建号（零角色）：先告知，再决定落点
      ElMessage.success('已根据飞书账号自动创建系统账号，等待管理员分配角色')
    }
    if (data.must_change_pwd) {
      ElMessage.warning('首次登录请先修改密码')
      router.replace('/change-password')
      return
    }
    await auth.fetchMe(true)
    if (auth.pendingRoles) {
      // 新账号还没有任何角色：/pending 是唯一可用的页面（其它路由都会 403）
      router.replace('/pending')
      return
    }
    router.replace(redirect)
  } catch (err: unknown) {
    // 后端对"未绑定（开关关闭时）/已停用/建号冲突/state 失效/飞书侧失败"都给了可读中文提示，直接透出
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = detail || '飞书登录失败，请稍后重试'
  } finally {
    busy.value = false
  }
})
</script>

<template>
  <div class="feishu-page">
    <div class="box">
      <h1>飞书登录</h1>
      <p v-if="busy" class="hint" aria-live="polite">正在校验飞书身份…</p>
      <template v-else>
        <p class="err" role="alert" aria-live="polite">{{ error }}</p>
        <el-button type="primary" size="large" class="full" @click="router.replace('/login')">
          返回登录页
        </el-button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.feishu-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1f2d3d 0%, #33475b 100%);
}
.box {
  width: 400px;
  background: #fff;
  border-radius: 8px;
  padding: 32px 34px;
  box-shadow: 0 18px 40px rgba(0, 0, 0, 0.25);
  text-align: center;
}
.box h1 { margin: 0 0 12px; font-size: var(--ctms-fs-lg); }
.hint { color: #6b7280; margin: 0; }
.err { color: #d93026; margin: 0 0 16px; }
.full { width: 100%; }
</style>
