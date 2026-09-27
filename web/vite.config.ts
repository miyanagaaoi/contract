import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发期将 /api 代理到后端 FastAPI（127.0.0.1:8000）
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
    /*
     * 文件监听必须排除两类"临时目录"，否则 dev server 会被直接打死：
     *
     * 1) 编辑器/工具/测试框架的**原子写**临时目录，形如
     *    `.ContractsView.vue.<pid>.<uuid>.tmpdir/`、`.xx.spec.ts.<pid>.<uuid>.tmpdir/`。
     *    这类目录可能出现在**任意源码目录下**（src/views、tests/e2e …），不只是测试目录；
     *    写入方在重命名前会占住其中的 .tmp 文件，chokidar 一旦 watch 到它就抛
     *    `Error: EBUSY: resource busy or locked, watch '…\.tmpdir\*.tmp'`，
     *    该错误是 FSWatcher 的 'error' 事件且无人接管 —— Node 进程随即退出，
     *    `npm run dev` 直接挂掉（实测复现，与本项目 Playwright 无关，是通用问题）。
     *
     * 2) 测试/报告产物目录，避免无谓的 HMR 抖动。
     */
    watch: {
      ignored: [
        /[\\/]\.[^\\/]*\.tmpdir[\\/]/,
        '**/tests/e2e/**',
        '**/test-results/**',
        '**/tests/e2e-report/**',
        '**/playwright-report/**',
      ],
    },
  },
  build: {
    rollupOptions: {
      output: {
        /*
         * T4-4：把体积最大的依赖拆成独立 chunk，改善部署后的缓存命中。
         *
         * 说明：`main.ts` 目前仍通过 `import * as ElementPlusIconsVue` 全量注册
         * 294 个图标，Rollup 无法 tree-shake 它。真正改成按需引入需要维护一份
         * 图标白名单——而 `MenuTree` 的图标名来自后端返回的字符串，漏一个就会让
         * 菜单图标静默空白（e2e 不覆盖图标）。对内网系统而言首屏体积不敏感，
         * 因此这里先做零风险的分包；按需引入留待有明确体积诉求时再做。
         */
        manualChunks: {
          'vendor-element-plus': ['element-plus', '@element-plus/icons-vue'],
          'vendor-vue': ['vue', 'vue-router', 'pinia'],
        },
      },
    },
  },
})
