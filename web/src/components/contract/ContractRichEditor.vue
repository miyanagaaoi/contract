<script setup lang="ts">
/**
 * 合同模板富文本编辑器（CR-048）：参考 TechFunWay/contract 的 RichEditor 方案，
 * 免第三方依赖（contenteditable + execCommand），支持标题/加粗/斜体/下划线/列表/对齐/撤销重做，
 * 以及“点击字段插入占位符 {{key}}”。
 *
 * 存储仍为 HTML（后端做白名单清洗）；与旧模板 HTML 完全兼容。
 */
import { onMounted, ref, watch } from 'vue'

const props = defineProps<{
  modelValue: string
  fields?: { key: string; label?: string }[]
  itemsTable?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const editorEl = ref<HTMLDivElement | null>(null)

const toolbar: { cmd: string; title: string; arg?: string; text: string }[] = [
  { cmd: 'bold', title: '加粗', text: 'B' },
  { cmd: 'italic', title: '斜体', text: 'I' },
  { cmd: 'underline', title: '下划线', text: 'U' },
  { cmd: 'strikeThrough', title: '删除线', text: 'S' },
  { cmd: 'insertUnorderedList', title: '无序列表', text: '• 列表' },
  { cmd: 'insertOrderedList', title: '有序列表', text: '1. 列表' },
  { cmd: 'justifyLeft', title: '左对齐', text: '左' },
  { cmd: 'justifyCenter', title: '居中', text: '中' },
  { cmd: 'justifyRight', title: '右对齐', text: '右' },
  { cmd: 'undo', title: '撤销', text: '↶' },
  { cmd: 'redo', title: '重做', text: '↷' },
  { cmd: 'removeFormat', title: '清除格式', text: '清除' },
]

const block: { value: string; label: string }[] = [
  { value: 'p', label: '正文' },
  { value: 'h1', label: '标题1' },
  { value: 'h2', label: '标题2' },
  { value: 'h3', label: '标题3' },
  { value: 'blockquote', label: '引用' },
]

function syncFromProps() {
  if (editorEl.value && props.modelValue !== editorEl.value.innerHTML) {
    editorEl.value.innerHTML = normalizeTokens(props.modelValue || '')
  }
}

onMounted(syncFromProps)
watch(() => props.modelValue, (val) => {
  // 正在编辑器内输入时不回写，避免光标重置
  const sel = window.getSelection()
  const editing = sel?.anchorNode && editorEl.value?.contains(sel.anchorNode)
  if (!editing) syncFromProps()
})

function emitValue() {
  if (editorEl.value) emit('update:modelValue', editorEl.value.innerHTML)
}

function exec(cmd: string, arg?: string) {
  editorEl.value?.focus()
  document.execCommand(cmd, false, arg)
  emitValue()
}

function onBlockChange(e: Event) {
  exec('formatBlock', (e.target as HTMLSelectElement).value)
}

/** 在光标处插入字段占位符（显示为可识别的高亮文本，保存仍为 {{key}}） */
function insertField(key: string, label?: string) {
  editorEl.value?.focus()
  const text = `【${label || key}】`
  const html = `<span class="ct-field" data-key="${key}">${text}</span>&nbsp;`
  document.execCommand('insertHTML', false, html)
  emitValue()
}

/** 把旧模板里的 {{key}} 占位符转成可读的【字段名】令牌（保存仍兼容后端两种格式） */
function normalizeTokens(raw: string): string {
  let out = raw || ''
  for (const f of props.fields || []) {
    const token = `<span class="ct-field" data-key="${f.key}">【${f.label || f.key}】</span>`
    out = out.split('{{' + f.key + '}}').join(token)
  }
  return out
}

/** 粘贴：优先保留富文本结构（后端会白名单清洗），否则纯文本 */
function insertToken(key: string, label: string) {
  editorEl.value?.focus()
  const html = `<span class="ct-field" data-key="${key}">【${label}】</span>&nbsp;`
  document.execCommand('insertHTML', false, html)
  emitValue()
}

function insertItemsTable() { insertToken('items_table', '标的物表格') }

/** 表格行/列调整（光标所在单元格）：+行 / -行 / -列 */
function tableOp(op: 'addRow' | 'delRow' | 'delCol') {
  const sel = window.getSelection()
  const node = sel?.anchorNode
  const el = node instanceof Element ? node : node?.parentElement
  const cell = el?.closest('td,th') as HTMLTableCellElement | null
  if (!cell) { return }
  const row = cell.parentElement as HTMLTableRowElement
  const table = cell.closest('table') as HTMLTableElement
  if (op === 'addRow') {
    const clone = row.cloneNode(true) as HTMLTableRowElement
    Array.from(clone.cells).forEach((c) => { c.innerHTML = '&nbsp;' })
    row.after(clone)
  } else if (op === 'delRow') {
    row.remove()
  } else {
    const idx = cell.cellIndex
    Array.from(table.rows).forEach((r) => r.cells[idx]?.remove())
  }
  emitValue()
}

function onPaste(e: ClipboardEvent) {
  e.preventDefault()
  const html = e.clipboardData?.getData('text/html')
  if (html) document.execCommand('insertHTML', false, html)
  else document.execCommand('insertText', false, e.clipboardData?.getData('text/plain') || '')
  emitValue()
}

function insertTable() {
  editorEl.value?.focus()
  const head = ['序号', '项目', '内容']
  const th = head.map((h) => `<th style="border:1px solid #cbd2da;padding:6px 8px">${h}</th>`).join('')
  const cells = (n: number) => Array.from({ length: n },
    () => '<td style="border:1px solid #cbd2da;padding:6px 8px">&nbsp;</td>').join('')
  const body = Array.from({ length: 2 }, (_, i) =>
    `<tr><td style="border:1px solid #cbd2da;padding:6px 8px">${i + 1}</td>${cells(2)}</tr>`).join('')
  const html = '<table border="1" cellspacing="0" cellpadding="6" '
    + 'style="border-collapse:collapse;width:100%">'
    + `<thead><tr>${th}</tr></thead><tbody>${body}</tbody></table><p><br/></p>`
  document.execCommand('insertHTML', false, html)
  emitValue()
}

/** 外部强制回填（导入 Word / 切换模板后用，绕开“编辑中不同步”的保护） */
function setContent(raw: string) {
  if (!editorEl.value) return
  editorEl.value.innerHTML = normalizeTokens(raw || '')
  emit('update:modelValue', editorEl.value.innerHTML)
}

defineExpose({ insertField, setContent })
</script>

<template>
  <div class="rich-editor">
    <div class="re-toolbar">
      <button v-for="b in toolbar" :key="b.cmd" type="button" class="re-btn" :title="b.title"
              @mousedown.prevent @click="exec(b.cmd)">{{ b.text }}</button>
      <span class="re-sep" />
      <el-select :model-value="'p'" size="small" style="width: 96px" title="段落格式"
                 @change="onBlockChange">
        <el-option v-for="o in block" :key="o.value" :label="o.label" :value="o.value" />
      </el-select>
      <template v-if="itemsTable">
        <span class="re-sep" />
        <button type="button" class="re-field" title="插入合同标的物表格（生成时按合同行项填充）"
                @mousedown.prevent @click="insertItemsTable">插入标的物表格</button>
        <button type="button" class="re-field" title="插入金额大写令牌（生成时按合同金额填充）"
                @mousedown.prevent @click="insertToken('amount_words', '金额大写')">金额大写</button>
        <button type="button" class="re-field" title="插入金额小写令牌"
                @mousedown.prevent @click="insertToken('amount_total', '金额小写')">金额小写</button>
        <button type="button" class="re-field" title="合同名称（自动取当前合同）"
                @mousedown.prevent @click="insertToken('contract_name', '合同名称')">合同名称</button>
        <button type="button" class="re-field" title="合同编号（自动取当前合同）"
                @mousedown.prevent @click="insertToken('contract_no', '合同编号')">合同编号</button>
        <button type="button" class="re-field" title="甲方名称（自动取当前合同）"
                @mousedown.prevent @click="insertToken('party_a', '甲方名称')">甲方名称</button>
        <button type="button" class="re-field" title="乙方名称（自动取当前合同）"
                @mousedown.prevent @click="insertToken('party_b', '乙方名称')">乙方名称</button>
        <button type="button" class="re-field" title="签订日期（自动取当前合同）"
                @mousedown.prevent @click="insertToken('sign_date', '签订日期')">签订日期</button>
      </template>
      <span class="re-sep" />
      <button type="button" class="re-btn" title="插入 3 列空白表格（可用 +行/-行/-列 调整）"
              @mousedown.prevent @click="insertTable">插入表格</button>
      <button type="button" class="re-btn" title="表格加一行" @mousedown.prevent @click="tableOp('addRow')">+行</button>
      <button type="button" class="re-btn" title="删除当前行" @mousedown.prevent @click="tableOp('delRow')">-行</button>
      <button type="button" class="re-btn" title="删除当前列" @mousedown.prevent @click="tableOp('delCol')">-列</button>
      <template v-if="(fields || []).length">
        <span class="re-sep" />
        <span class="re-hint">插入字段：</span>
        <button v-for="f in fields" :key="f.key" type="button" class="re-field"
                :title="`插入【${f.label || f.key}】`" @mousedown.prevent @click="insertField(f.key, f.label)">
          {{ f.label || f.key }}
        </button>
      </template>
    </div>
    <div ref="editorEl" class="re-body" contenteditable="true"
         data-placeholder="在此撰写合同正文，点击右侧/上方字段按钮插入占位符…"
         @input="emitValue" @blur="emitValue" @paste="onPaste" />
  </div>
</template>

<style scoped>
.rich-editor { border: 1px solid var(--el-border-color); border-radius: 4px; overflow: hidden; }
.re-toolbar { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; padding: 6px 8px;
  border-bottom: 1px solid var(--el-border-color-lighter); background: var(--el-fill-color-light); }
.re-btn, .re-field { border: 1px solid var(--el-border-color); background: #fff; cursor: pointer;
  border-radius: 3px; font-size: 12px; padding: 3px 8px; color: var(--el-text-color-regular); }
.re-btn:hover, .re-field:hover { border-color: var(--el-color-primary); color: var(--el-color-primary); }
.re-field { background: #f1f8f7; color: #0e4f4a; border-color: #cbe3e0; }
.re-hint { font-size: 12px; color: var(--el-text-color-secondary); }
.re-sep { width: 1px; height: 18px; background: var(--el-border-color); margin: 0 4px; }
.re-body { min-height: 320px; max-height: 60vh; overflow-y: auto; padding: 16px 20px;
  outline: none; line-height: 1.8; font-size: 14px; }
.re-body:empty::before { content: attr(data-placeholder); color: var(--el-text-color-placeholder); }
.re-body :deep(h1) { font-size: 20px; text-align: center; margin: 8px 0 16px; }
.re-body :deep(h2) { font-size: 16px; margin: 14px 0 8px; }
.re-body :deep(h3) { font-size: 14px; margin: 12px 0 6px; }
.re-body :deep(blockquote) { margin: 8px 0; padding-left: 10px; border-left: 3px solid #cbe3e0;
  color: #5a6672; }
.re-body :deep(table) { border-collapse: collapse; width: 100%; margin: 8px 0; }
.re-body :deep(td), .re-body :deep(th) { border: 1px solid var(--el-border-color); padding: 6px 8px;
  vertical-align: top; }
.re-body :deep(img) { max-width: 100%; height: auto; }
.re-body :deep(ul), .re-body :deep(ol) { margin: 6px 0 6px 22px; }
.re-body :deep(li) { margin: 2px 0; }
.re-body :deep(.ct-field) { display: inline-block; padding: 0 6px; border-radius: 4px;
  background: #f1f8f7; color: #0e4f4a; border: 1px solid #cbe3e0; font-weight: 600; }
</style>
