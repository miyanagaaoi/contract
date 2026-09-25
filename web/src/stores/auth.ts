/**
 * 登录态与权限（V2.0）。
 *
 * 数据来源：`GET /api/auth/me` → { user, roles, perms[], menus[] }
 * - 令牌存 localStorage（内网低风险，不做 refresh token，过期重新登录）
 * - 权限判定：`hasPerm(code)`；前端判权仅为体验，**服务端仍强制校验**（AC-V2-41）
 * - 菜单树由后端按权限裁剪后返回，前端只渲染（避免前后端两套定义）
 */
import { defineStore } from 'pinia'

import { TOKEN_KEY, http } from '@/api'

export interface AuthUser {
  id: number
  username: string
  real_name: string
  org_id: number | null
  org_name: string | null
  is_superadmin: boolean
  must_change_pwd: boolean
}

export interface RoleBrief {
  id: number
  code: string
  name: string
  data_scope: string
}

export interface MenuNode {
  key: string
  title: string
  path?: string
  icon?: string
  perm: string
  children?: MenuNode[]
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || '',
    user: null as AuthUser | null,
    roles: [] as RoleBrief[],
    perms: [] as string[],
    menus: [] as MenuNode[],
    loaded: false,
  }),

  getters: {
    isLoggedIn: (state) => !!state.token,
    isSuperadmin: (state) => !!state.user?.is_superadmin,
    displayName: (state) => state.user?.real_name || state.user?.username || '',
  },

  actions: {
    setToken(token: string) {
      this.token = token
      if (token) localStorage.setItem(TOKEN_KEY, token)
      else localStorage.removeItem(TOKEN_KEY)
    },

    /** 是否有某权限点（超管恒真） */
    hasPerm(code: string) {
      if (this.user?.is_superadmin) return true
      return this.perms.includes(code)
    },

    async login(username: string, password: string) {
      const { data } = await http.post('/auth/login', { username, password })
      this.setToken(data.token)
      this.user = data.user as AuthUser
      return data as { must_change_pwd: boolean; user: AuthUser }
    },

    /** 拉取当前用户与权限（已加载则跳过；force=true 强制刷新） */
    async fetchMe(force = false) {
      if (this.loaded && !force) return
      const { data } = await http.get('/auth/me')
      this.user = data.user
      this.roles = data.roles || []
      this.perms = data.perms || []
      this.menus = data.menus || []
      this.loaded = true
    },

    async changePassword(oldPassword: string, newPassword: string) {
      await http.post('/auth/change-password', {
        old_password: oldPassword,
        new_password: newPassword,
      })
      if (this.user) this.user.must_change_pwd = false
      this.loaded = false
    },

    async logout() {
      try {
        await http.post('/auth/logout')
      } catch {
        // 令牌可能已失效，忽略
      }
      this.setToken('')
      this.user = null
      this.roles = []
      this.perms = []
      this.menus = []
      this.loaded = false
    },
  },
})
