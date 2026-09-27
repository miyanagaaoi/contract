<script setup lang="ts">
/**
 * 打印模板编辑（V2.2 / BR-V2.2-02）。
 *
 * 单据打印的 A4 版面此前**写死在 `print_service.py`** 里：改个标题、把"仓库"挪到
 * 表头第一格、把签字栏的"领料/收货"改成"领用人"，都得改代码发版。本页把版面
 * 抽成可视化配置，管理员自己就能调：
 *
 * - **文字信息**：标题 / 副标题 / 页脚、是否附打印时间；
 * - **组件放置位置**：四个区块（标题区 / 表头信息 / 行项明细 / 签字与备注）的整体
 *   先后顺序；表头字段与行项列的先后顺序（↑↓）、是否显示、是否独占整行；
 *   表头每行放几个字段；
 * - **文字信息（字段级）**：表头字段标签、行项列标签、签字栏文字（可增删改序）。
 *
 * 交互要点：
 * 1. 右侧 iframe 用后端返回的 HTML 做**实时预览**（编辑后 700ms 去抖自动刷新），
 *    预览走"提交当前配置"的接口，因此**未保存的改动也能看到效果**；
 * 2. 切换单据类型前若有未保存改动会先确认，避免调了半天白调；
 * 3. 保存由后端归一化（未知字段丢弃、非法值回落），本页不做第二套校验。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  fetchPrintTemplate,
  fetchPrintTemplates,
  previewPrintTemplate,
  resetPrintTemplate,
  savePrintTemplate,
  type Dict,
} from '@/api'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canEdit = computed(() => auth.hasPerm('system.print.edit'))

const loading = ref(false)
const saving = ref(false)

const summaries = ref<Dict[]>([])
const meta = ref<Dict>({})
const currentKind = ref('')
const config = ref<Dict | null>(null)
const factory = ref<Dict | null>(null)
const customized = ref(false)
const updatedAt = ref<string | null>(null)
const updatedByName = ref<string | null>(null)
const dirty = ref(false)
const loadError = ref('')
/** 折叠面板默认全部展开：调版面时最常做的是在几个区块之间来回切换 */
const openPanels = ref<string[]>(['text', 'blocks', 'head', 'items', 'sign'])

/**
 * 服务端回填期间抑制脏标记。
 *
 * `flush: 'sync'` 是必需的：回填与抑制标志在同一个同步区间内完成，
 * 默认的 pre flush 会等到区间退出后才回调，标志早已失效（与 DocFormPage 同因）。
 */
let suppressDirty = false

// ---------------- 预览 ----------------
const previewHtml = ref('')
const previewLoading = ref(false)
const previewError = ref('')
let previewTimer: number | undefined

const currentLabel = computed(() => (
  summaries.value.find((s) => s.kind === currentKind.value)?.label as string
) || meta.value.kinds?.find((k: Dict) => k.kind === currentKind.value)?.label || '单据')

/** 表头字段/行项列的**原始**名称（重命名后仍能认出这是哪个字段） */
function originLabel(key: string, group: 'head_fields' | 'item_columns'): string {
  const hit = (meta.value[group] as Dict[] | undefined)?.find((row) => row.key === key)
  return (hit?.label as string) || key
}

function blockLabel(key: string): string {
  const hit = (meta.value.blocks as Dict[] | undefined)?.find((row) => row.key === key)
  return (hit?.label as string) || key
}

function blockNote(key: string): string {
  const hit = (meta.value.blocks as Dict[] | undefined)?.find((row) => row.key === key)
  return (hit?.note as string) || ''
}

function isCustomized(kind: string): boolean {
  return !!summaries.value.find((s) => s.kind === kind)?.customized
}

// ---------------- 列表与加载 ----------------

async function loadSummaries() {
  const data = await fetchPrintTemplates()
  summaries.value = data.items ?? []
  meta.value = data.meta ?? {}
}

async function selectKind(kind: string) {
  if (kind === currentKind.value) return
  if (dirty.value && canEdit.value) {
    try {
      await ElMessageBox.confirm('当前模板有未保存的修改，确定切换单据类型？', '未保存的修改', {
        type: 'warning', confirmButtonText: '放弃修改并切换', cancelButtonText: '留在本页',
      })
    } catch {
      return
    }
  }
  currentKind.value = kind
  loading.value = true
  loadError.value = ''
  try {
    const detail = await fetchPrintTemplate(kind)
    suppressDirty = true
    config.value = detail.config as Dict
    suppressDirty = false
    factory.value = detail.factory as Dict
    customized.value = !!detail.customized
    updatedAt.value = (detail.updated_at as string) ?? null
    updatedByName.value = (detail.updated_by_name as string) ?? null
    dirty.value = false
    await doPreview()
  } catch (error) {
    // 不能让异常静默消失：失败时编辑器不渲染，用户只会看到一片空白
    loadError.value = (error as Error)?.message || '模板加载失败，请刷新重试'
  } finally {
    loading.value = false
  }
}

// ---------------- 预览（去抖） ----------------

function schedulePreview() {
  if (!config.value || !currentKind.value) return
  window.clearTimeout(previewTimer)
  previewTimer = window.setTimeout(() => { void doPreview() }, 700)
}

async function doPreview() {
  if (!config.value || !currentKind.value) return
  previewLoading.value = true
  previewError.value = ''
  try {
    previewHtml.value = await previewPrintTemplate(currentKind.value, config.value)
  } catch {
    previewError.value = '预览渲染失败，请检查配置后重试'
  } finally {
    previewLoading.value = false
  }
}

watch(config, () => {
  if (!suppressDirty) dirty.value = true
  schedulePreview()
}, { deep: true, flush: 'sync' })

// ---------------- 排序 ----------------

function moveUp(list: Dict[], index: number) {
  if (index <= 0) return
  const [item] = list.splice(index, 1)
  list.splice(index - 1, 0, item)
}

function moveDown(list: Dict[], index: number) {
  if (index >= list.length - 1) return
  const [item] = list.splice(index, 1)
  list.splice(index + 1, 0, item)
}

// ---------------- 签字栏 ----------------

function addSignLabel() {
  if (!config.value) return
  const list = config.value.signature_labels as string[]
  const max = (meta.value.max_sign_labels as number) || 8
  if (list.length >= max) {
    ElMessage.warning(`签字栏最多 ${max} 项`)
    return
  }
  list.push('新签字栏')
}

function removeSignLabel(index: number) {
  const list = config.value?.signature_labels as string[] | undefined
  if (!list || list.length <= 1) {
    ElMessage.warning('至少保留一项签字栏')
    return
  }
  list.splice(index, 1)
}

// ---------------- 保存 / 恢复 ----------------

async function save() {
  if (!config.value || !currentKind.value) return
  saving.value = true
  try {
    await savePrintTemplate(currentKind.value, config.value)
    ElMessage.success(`已保存「${currentLabel.value}」打印模板`)
    dirty.value = false
    await loadSummaries()
    customized.value = isCustomized(currentKind.value)
  } catch {
    // 拦截器已提示
  } finally {
    saving.value = false
  }
}

async function resetToFactory() {
  if (!currentKind.value) return
  try {
    await ElMessageBox.confirm(
      `将「${currentLabel.value}」的打印模板恢复为出厂版面，自定义内容会丢失。确定继续？`,
      '恢复默认模板', { type: 'warning', confirmButtonText: '恢复默认', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const data = await resetPrintTemplate(currentKind.value)
    suppressDirty = true
    config.value = data.config as Dict
    suppressDirty = false
    factory.value = data.config as Dict
    customized.value = false
    dirty.value = false
    await loadSummaries()
    await doPreview()
    ElMessage.success('已恢复出厂模板')
  } catch {
    // 拦截器已提示
  }
}

/** 一键对齐出厂版面（只改前端内存，仍需点保存） */
async function copyFactory() {
  if (!factory.value) return
  config.value = JSON.parse(JSON.stringify(factory.value))
  ElMessage.info('已载入出厂版面，确认无误后点「保存模板」')
}

onMounted(async () => {
  loading.value = true
  try {
    await loadSummaries()
    const first = (meta.value.kinds as Dict[] | undefined)?.[0]?.kind as string | undefined
    if (first) await selectKind(first)
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-loading="loading" class="print-tpl">
    <el-card shadow="never" class="mb">
      <template #header>
        <div class="head">
          <div>
            <span class="title">打印模板</span>
            <span class="subtitle">调整单据打印（A4）的版面与文字；未保存的改动会实时预览</span>
          </div>
          <div>
            <el-button v-if="canEdit" :disabled="!config" @click="copyFactory">载入出厂版面</el-button>
            <el-button v-if="canEdit" type="danger" plain :disabled="!customized" @click="resetToFactory">
              恢复默认
            </el-button>
            <el-button v-if="canEdit" type="primary" :loading="saving" :disabled="!config" @click="save">
              保存模板
            </el-button>
          </div>
        </div>
      </template>
      <el-alert v-if="!canEdit" type="info" :closable="false" show-icon
                title="你没有「打印模板维护」（system.print.edit）权限，当前为只读查看。" />
      <el-alert v-if="loadError" type="error" :closable="false" show-icon class="mt"
                title="模板加载失败" :description="loadError" />
    </el-card>

    <el-row :gutter="12">
      <!-- ---------- 左：单据类型 ---------- -->
      <el-col :xs="24" :sm="6" :md="5" :lg="4">
        <el-card shadow="never" class="side">
          <div v-for="s in summaries" :key="s.kind as string" class="kind-item"
               :class="{ active: s.kind === currentKind }" @click="selectKind(s.kind as string)">
            <span class="kind-name">{{ s.label }}</span>
            <el-tag v-if="s.customized" size="small" type="warning" effect="plain">已自定义</el-tag>
          </div>
        </el-card>
      </el-col>

      <!-- ---------- 中：编辑 ---------- -->
      <el-col :xs="24" :sm="18" :md="11" :lg="11">
        <el-card v-if="config" shadow="never" class="editor">
          <el-alert v-if="customized && updatedAt" type="success" :closable="false" show-icon class="mb"
                    :title="`当前为自定义模板（${updatedByName || '未知'} 于 ${updatedAt} 修改）`" />

          <el-collapse v-model="openPanels">
            <!-- 文字信息 -->
            <el-collapse-item name="text" title="① 文字信息">
              <el-form label-width="96px" :disabled="!canEdit" size="small">
                <el-form-item label="单据标题">
                  <el-input v-model="config.title" maxlength="64" show-word-limit
                            placeholder="打印在正上方的单据名称" />
                </el-form-item>
                <el-form-item label="副标题">
                  <el-input v-model="config.subtitle" maxlength="96" placeholder="标题下方的小字（可留空）" />
                </el-form-item>
                <el-form-item label="附打印时间">
                  <el-switch v-model="config.show_printed_at" />
                  <span class="tip">开启后副标题里会追加「打印时间 2025-01-01 10:00」</span>
                </el-form-item>
                <el-form-item label="页脚文字">
                  <el-input v-model="config.footer" maxlength="200" placeholder="页面最下方的一行说明" />
                </el-form-item>
              </el-form>
            </el-collapse-item>

            <!-- 区块顺序 -->
            <el-collapse-item name="blocks" title="② 区块顺序（组件的上下位置）">
              <div v-for="(key, i) in config.blocks" :key="key as string" class="row-item">
                <span class="drag">☰</span>
                <span class="row-name">{{ blockLabel(key as string) }}</span>
                <span class="row-note">{{ blockNote(key as string) }}</span>
                <span class="spacer" />
                <el-button size="small" text :disabled="!canEdit || i === 0"
                           @click="moveUp(config.blocks, i)">↑ 上移</el-button>
                <el-button size="small" text :disabled="!canEdit || i === config.blocks.length - 1"
                           @click="moveDown(config.blocks, i)">↓ 下移</el-button>
              </div>
            </el-collapse-item>

            <!-- 表头字段 -->
            <el-collapse-item name="head" title="③ 表头信息（字段 / 标签 / 位置）">
              <el-form label-width="96px" :disabled="!canEdit" size="small" class="mb">
                <el-form-item label="每行字段数">
                  <el-radio-group v-model="config.head_columns">
                    <el-radio-button v-for="n in (meta.head_column_choices || [1, 2, 3])" :key="n" :value="n">
                      {{ n }} 列
                    </el-radio-button>
                  </el-radio-group>
                </el-form-item>
              </el-form>
              <div v-for="(f, i) in config.head_fields" :key="f.key as string" class="row-item">
                <el-switch v-model="f.enabled" size="small" :disabled="!canEdit" />
                <span class="row-name" :class="{ off: !f.enabled }">
                  {{ originLabel(f.key as string, 'head_fields') }}
                </span>
                <el-input v-model="f.label" size="small" class="label-input" maxlength="32"
                          :disabled="!canEdit || !f.enabled" placeholder="打印出来的标签" />
                <el-checkbox v-model="f.full" size="small" :disabled="!canEdit || !f.enabled">独占整行</el-checkbox>
                <el-button size="small" text :disabled="!canEdit || i === 0"
                           @click="moveUp(config.head_fields, i)">↑</el-button>
                <el-button size="small" text :disabled="!canEdit || i === config.head_fields.length - 1"
                           @click="moveDown(config.head_fields, i)">↓</el-button>
              </div>
              <div class="tip-line">
                提示：单据上没有的字段（如采购单没有「入库类型」）会自动跳过，不会印出空白格。
              </div>
            </el-collapse-item>

            <!-- 行项列 -->
            <el-collapse-item name="items" title="④ 行项明细（列 / 标签 / 顺序）">
              <div v-for="(c, i) in config.item_columns" :key="c.key as string" class="row-item">
                <el-switch v-model="c.enabled" size="small" :disabled="!canEdit" />
                <span class="row-name" :class="{ off: !c.enabled }">
                  {{ originLabel(c.key as string, 'item_columns') }}
                </span>
                <el-input v-model="c.label" size="small" class="label-input" maxlength="32"
                          :disabled="!canEdit || !c.enabled" placeholder="打印出来的列名" />
                <el-button size="small" text :disabled="!canEdit || i === 0"
                           @click="moveUp(config.item_columns, i)">↑</el-button>
                <el-button size="small" text :disabled="!canEdit || i === config.item_columns.length - 1"
                           @click="moveDown(config.item_columns, i)">↓</el-button>
              </div>
              <div class="tip-line">提示：至少需要保留一列；金额列开启时会自动带「合计」行。</div>
            </el-collapse-item>

            <!-- 签字与备注 -->
            <el-collapse-item name="sign" title="⑤ 签字栏与备注">
              <el-form label-width="96px" :disabled="!canEdit" size="small">
                <el-form-item label="审批信息">
                  <el-switch v-model="config.show_approval" />
                  <span class="tip">制单人、提交时间、审核时间</span>
                </el-form-item>
                <el-form-item label="打印备注">
                  <el-switch v-model="config.show_remarks" />
                  <span class="tip">单据备注非空时打印</span>
                </el-form-item>
                <el-form-item label="作废说明">
                  <el-switch v-model="config.show_void_note" />
                  <span class="tip">已作废单据打印作废原因</span>
                </el-form-item>
                <el-form-item label="签字栏">
                  <div class="sign-list">
                    <div v-for="(name, i) in config.signature_labels" :key="i" class="sign-row">
                      <el-input v-model="config.signature_labels[i]" size="small" maxlength="24"
                                :disabled="!canEdit" />
                      <el-button size="small" text :disabled="!canEdit" @click="moveUp(config.signature_labels, i)"
                                 :style="{ visibility: i === 0 ? 'hidden' : 'visible' }">↑</el-button>
                      <el-button size="small" text :disabled="!canEdit"
                                 :style="{ visibility: i === config.signature_labels.length - 1 ? 'hidden' : 'visible' }"
                                 @click="moveDown(config.signature_labels, i)">↓</el-button>
                      <el-button size="small" text type="danger" :disabled="!canEdit"
                                 @click="removeSignLabel(i)">删除</el-button>
                    </div>
                    <el-button size="small" :disabled="!canEdit" @click="addSignLabel">＋ 增加签字栏</el-button>
                  </div>
                </el-form-item>
              </el-form>
            </el-collapse-item>
          </el-collapse>
        </el-card>
        <el-empty v-else description="正在加载模板…" />
      </el-col>

      <!-- ---------- 右：预览 ---------- -->
      <el-col :xs="24" :sm="24" :md="8" :lg="9">
        <el-card shadow="never" class="preview-card">
          <template #header>
            <div class="head">
              <span class="title">实时预览</span>
              <span>
                <span v-if="dirty" class="dirty-dot">未保存</span>
                <el-button size="small" :loading="previewLoading" @click="doPreview">刷新预览</el-button>
              </span>
            </div>
          </template>
          <el-alert v-if="previewError" type="error" :closable="false" show-icon :title="previewError" />
          <iframe v-else class="preview-frame" title="打印预览" :srcdoc="previewHtml" />
          <div class="tip-line">
            预览使用系统内置的样例单据（不读取业务数据），改完记得点「保存模板」。
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script lang="ts">
export default { name: 'PrintTemplateView' }
</script>

<style scoped>
.mb { margin-bottom: var(--ctms-gap); }
.mt { margin-top: var(--ctms-gap); }
.head { display: flex; align-items: center; justify-content: space-between; gap: var(--ctms-gap); }
.title { font-weight: 600; font-size: var(--ctms-fs-md); }
.subtitle { margin-left: 10px; color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); }
.side { min-height: 200px; }
.kind-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 8px 10px;
  border-radius: var(--ctms-radius);
  cursor: pointer;
  font-size: var(--ctms-fs-base);
}
.kind-item:hover { background: var(--el-fill-color-light); }
.kind-item.active { background: var(--el-color-primary-light-9); color: var(--el-color-primary); font-weight: 600; }
.row-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
  border-bottom: 1px dashed var(--el-border-color-lighter);
}
.row-item:last-child { border-bottom: none; }
.drag { color: var(--ctms-text-placeholder); cursor: default; }
.row-name { min-width: 84px; color: var(--ctms-text-secondary); font-size: var(--ctms-fs-sm); }
.row-name.off { color: var(--ctms-text-placeholder); text-decoration: line-through; }
.row-note { color: var(--ctms-text-muted); font-size: var(--ctms-fs-xs); }
.label-input { width: 140px; }
.spacer { flex: 1; }
.tip { margin-left: 8px; color: var(--ctms-text-muted); font-size: var(--ctms-fs-xs); }
.tip-line { margin-top: 6px; color: var(--ctms-text-muted); font-size: var(--ctms-fs-xs); }
.sign-list { width: 100%; }
.sign-row { display: flex; align-items: center; gap: 4px; margin-bottom: 4px; }
.preview-card { position: sticky; top: 12px; }
.preview-frame {
  width: 100%;
  height: 68vh;
  min-height: 420px;
  border: 1px solid var(--el-border-color);
  border-radius: var(--ctms-radius);
  background: #fff;
}
.dirty-dot { margin-right: 8px; color: var(--ctms-warning-text); font-size: var(--ctms-fs-xs); }
</style>
