<script setup lang="ts">
/**
 * 手写签名画板（原生 Canvas 自绘，不引入 signature_pad 等第三方库）。
 *
 * 为什么不用 signature_pad：项目惯例是零新增依赖，而签名采集只需要
 * 「落笔—拖动—抬笔 + 导出 PNG」这一点点功能，原生 Canvas API 完全够用，
 * 引库反而增加包体与维护面。
 */
import { onMounted, ref } from 'vue'

const emit = defineEmits<{ (e: 'save', blob: Blob): void }>()

// V2.6.1：宽高改为响应式（全屏书写时按视口尺寸重算）
const W = ref(400)     // CSS 逻辑宽度（px）
const H = ref(160)     // CSS 逻辑高度（px）
const fullscreen = ref(false)
const canvasRef = ref<HTMLCanvasElement | null>(null)
const hasInk = ref(false)   // 是否已落笔（空画板禁用保存按钮）
const drawing = ref(false)
/** 上一触点坐标（CSS 逻辑坐标），用于 lineTo 连线 */
let last = { x: 0, y: 0 }
let ctx: CanvasRenderingContext2D | null = null

/** 初始化画板：按 devicePixelRatio 放大实际像素，绘制时坐标乘 dpr，防高分屏模糊 */
onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return
  const dpr = window.devicePixelRatio || 1
  canvas.width = W.value * dpr
  canvas.height = H.value * dpr
  ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.scale(dpr, dpr)
  ctx.lineWidth = 3
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.strokeStyle = '#1a1a1a'   // 深色打印友好
  // 背景保持透明：打印纸本身是白的，透明 PNG 嵌入打印 HTML 更干净；
  // toBlob('image/png') 原生支持透明通道，无需填白。
})

function pos(e: MouseEvent | Touch): { x: number; y: number } {
  const rect = canvasRef.value!.getBoundingClientRect()
  return { x: e.clientX - rect.left, y: e.clientY - rect.top }
}

function start(p: { x: number; y: number }) {
  if (!ctx) return
  drawing.value = true
  hasInk.value = true
  last = p
  // 落笔画一个小点（单击也能留痕）：round cap 下零长度线段也会渲染圆点
  ctx.beginPath()
  ctx.moveTo(p.x, p.y)
  ctx.lineTo(p.x + 0.01, p.y)
  ctx.stroke()
}

function move(p: { x: number; y: number }) {
  if (!drawing.value || !ctx) return
  // 签名场景对平滑度要求不高，lineTo 即可（quadraticCurveTo 收益有限）
  ctx.beginPath()
  ctx.moveTo(last.x, last.y)
  ctx.lineTo(p.x, p.y)
  ctx.stroke()
  last = p
}

// ---- 鼠标事件 ----
function onMouseDown(e: MouseEvent) { start(pos(e)) }
function onMouseMove(e: MouseEvent) { move(pos(e)) }
function onMouseUp() { drawing.value = false }

// ---- 触屏事件（preventDefault 阻止页面滚动/下拉刷新打断书写） ----
function onTouchStart(e: TouchEvent) {
  e.preventDefault()
  start(pos(e.touches[0]))
}
function onTouchMove(e: TouchEvent) {
  e.preventDefault()
  move(pos(e.touches[0]))
}
function onTouchEnd(e: TouchEvent) {
  e.preventDefault()
  if (e.touches.length === 0) drawing.value = false
}

/** 按目标逻辑尺寸重建画板，并把已有笔迹等比保留（V2.6.1 全屏切换用） */
function resizeCanvas(w: number, h: number) {
  const canvas = canvasRef.value
  if (!canvas) return
  const snapshot = hasInk.value ? canvas.toDataURL('image/png') : ''
  W.value = w
  H.value = h
  const dpr = window.devicePixelRatio || 1
  canvas.width = w * dpr
  canvas.height = h * dpr
  const next = canvas.getContext('2d')
  if (!next) return
  ctx = next
  ctx.scale(dpr, dpr)
  ctx.lineWidth = 3
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.strokeStyle = '#1a1a1a'
  if (snapshot) {
    const img = new Image()
    img.onload = () => { ctx?.drawImage(img, 0, 0, w, h) }
    img.src = snapshot
  }
}

/** 进入全屏书写（手机端小屏书写体验，V2.6.1） */
function enterFullscreen() {
  fullscreen.value = true
  // 视口尺寸减去顶部工具区与底部按钮区，留出书写空间
  const w = Math.max(320, window.innerWidth - 24)
  const h = Math.max(200, window.innerHeight - 160)
  // 等遮罩渲染完成后再重设，避免读到旧尺寸
  setTimeout(() => resizeCanvas(w, h), 30)
}

/** 退出全屏，恢复默认画板尺寸 */
function exitFullscreen() {
  fullscreen.value = false
  setTimeout(() => resizeCanvas(400, 160), 30)
}

/** 清空画板（供按钮和父组件 reset 调用） */
function reset() {
  if (!ctx) return
  ctx.clearRect(0, 0, W.value, H.value)
  hasInk.value = false
}

/** 导出 PNG：背景透明（打印纸本身是白的，透明 PNG 嵌入打印 HTML 更干净） */
function save() {
  const canvas = canvasRef.value
  if (!canvas || !hasInk.value) return
  canvas.toBlob((blob) => {
    if (blob) emit('save', blob)
  }, 'image/png')
}

defineExpose({ reset })
</script>

<template>
  <div class="sigpad" :class="{ 'sigpad--fullscreen': fullscreen }">
    <canvas
      ref="canvasRef"
      class="sigpad-canvas"
      @mousedown="onMouseDown"
      @mousemove="onMouseMove"
      @mouseup="onMouseUp"
      @mouseleave="onMouseUp"
      @touchstart="onTouchStart"
      @touchmove="onTouchMove"
      @touchend="onTouchEnd"
    />
    <div class="sigpad-tip gray">鼠标拖动或手指书写；保存后生成 PNG 并上传为该账号的电子签名</div>
    <div class="sigpad-actions">
      <el-button size="small" @click="reset">清空重写</el-button>
      <el-button v-if="!fullscreen" size="small" @click="enterFullscreen">
        全屏书写
      </el-button>
      <el-button v-else size="small" @click="exitFullscreen">退出全屏</el-button>
      <el-button type="primary" size="small" :disabled="!hasInk" @click="save">
        保存手写签名
      </el-button>
    </div>
  </div>
</template>

<style scoped>
/* V2.6.1：全屏书写模式（移动端重点，桌面端也可用） */
.sigpad--fullscreen {
  position: fixed;
  inset: 0;
  z-index: 3000;
  background: #fff;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sigpad--fullscreen .sigpad-canvas {
  width: 100% !important;
  max-width: none;
  height: calc(100vh - 150px) !important;
  flex: 1;
  border-radius: 0;
}
.sigpad--fullscreen .sigpad-actions { margin-top: auto; }
.sigpad-canvas {
  width: 400px;
  max-width: 100%;
  height: 160px;
  border: 1px dashed var(--el-border-color);
  border-radius: 4px;
  background: #fff;   /* 仅页面展示时垫白（画板内部像素仍是透明背景） */
  cursor: crosshair;
  touch-action: none; /* 触屏书写时不让浏览器接管手势 */
  display: block;
}
.sigpad-tip { margin-top: 6px; font-size: var(--ctms-fs-sm, 12px); }
.sigpad-actions { margin-top: 8px; display: flex; gap: 8px; }
.gray { color: var(--ctms-text-muted, #909399); }
</style>
