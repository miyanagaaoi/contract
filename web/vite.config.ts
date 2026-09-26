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
})
