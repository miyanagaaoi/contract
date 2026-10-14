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

const W = 400          // CSS 逻辑宽度（px）
const H = 160          // CSS 逻辑高度（px）
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
  canvas.width = W * dpr
  canvas.height = H * dpr
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

/** 清空画板（供按钮和父组件 reset 调用） */
function reset() {
  if (!ctx) return
  ctx.clearRect(0, 0, W, H)
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
  <div class="sigpad">
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
      <el-button type="primary" size="small" :disabled="!hasInk" @click="save">
        保存手写签名
      </el-button>
    </div>
  </div>
</template>

<style scoped>
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
