<script setup lang="ts">
/**
 * 物料树形选择器（V2.6.1 / CR-021）：商品类型分组 → 物料，悬停显示档案信息。
 *
 * 从「新增合同」的行项物料选择提炼而来，单据行项（DocItemsTable）与合同行项共用：
 * - 树形展开：按 `product_type_name` 分组，组节点不可选；
 * - 悬停提示：编码/名称/规格/单位/默认单价/类型，辅助选料；
 * - 搜索：本地按名称/编码过滤；输入 ≥2 字时再向后端按关键词拉取，
 *   避免物料超过首屏 50 条时搜不到（后端 options 默认 limit=50）；
 * - 选中后通过 `change` 事件抛出完整物料对象，由调用方带出快照字段。
 */
import { computed, onMounted, ref } from 'vue'

import { fetchMasterOptions, type Dict } from '@/api'

const props = withDefaults(defineProps<{
  /** 选中物料 id（v-model） */
  modelValue?: number | null
  placeholder?: string
  disabled?: boolean
  size?: 'small' | 'default' | 'large'
  /** 多选（盘点单「按物料生成行项」等场景） */
  multiple?: boolean
}>(), {
  modelValue: null,
  placeholder: '按类型展开选择，或输入编码/名称搜索',
  disabled: false,
  size: 'small',
  multiple: false,
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: number | number[] | null): void
  (e: 'change', product: Dict | Dict[] | null): void
}>()

const products = ref<Dict[]>([])
const loading = ref(false)
let remoteTimer: ReturnType<typeof setTimeout> | null = null

async function load(keyword = '') {
  loading.value = true
  try {
    products.value = await fetchMasterOptions('product', keyword ? { keyword } : {})
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

onMounted(() => load())

/** 产品类型分组 → 物料叶子节点 */
const treeData = computed<Dict[]>(() => {
  const groups = new Map<string, Dict[]>()
  for (const p of products.value) {
    const key = (p.product_type_name as string) || '未分类'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push({
      id: p.id,
      label: `${p.name}（${p.code}）`,
      raw: p,
    })
  }
  return [...groups.entries()].map(([name, children]) => ({
    id: `t:${name}`,
    label: `${name}（${children.length}）`,
    disabled: true,
    isGroup: true,
    children,
  }))
})

const inner = computed({
  get: () => props.multiple ? ((props.modelValue as number[] | null) ?? []) : (props.modelValue ?? null),
  set: (v: number | number[] | null) => {
    emit('update:modelValue', v)
    if (props.multiple) {
      const ids = Array.isArray(v) ? v : []
      emit('change', products.value.filter((p) => ids.includes(p.id as number)))
      return
    }
    const hit = products.value.find((p) => p.id === v) || null
    emit('change', hit)
  },
})

/** 树节点过滤：组节点看子节点是否命中 */
function filterNode(query: string, data: Dict): boolean {
  const q = (query || '').trim().toLowerCase()
  if (!q) return true
  if (data.isGroup) {
    return (data.children || []).some((c: Dict) =>
      String(c.label || '').toLowerCase().includes(q))
  }
  return String(data.label || '').toLowerCase().includes(q)
}

/** 输入 ≥2 字时按关键词远程补拉（树选择继承 el-select 的 remote/remote-method） */
function onRemoteSearch(query: string) {
  if (remoteTimer) clearTimeout(remoteTimer)
  const q = (query || '').trim()
  if (!q) {
    load('')
    return
  }
  if (q.length < 2) return
  remoteTimer = setTimeout(() => { load(q) }, 250)
}

/** 悬停提示内容 */
function tip(p: Dict | undefined): string {
  if (!p) return ''
  return [
    `编码：${p.code ?? '—'}`,
    `名称：${p.name ?? '—'}`,
    `规格：${p.spec || '—'}`,
    `单位：${p.uom_name || '—'}`,
    `默认单价：${p.default_price ?? '—'}`,
    `类型：${p.product_type_name || '未分类'}`,
  ].join(' ｜ ')
}

defineExpose({ load, products })
</script>

<template>
  <el-tree-select
    v-model="inner"
    :data="treeData"
    :size="size"
    :disabled="disabled"
    :placeholder="placeholder"
    :loading="loading"
    filterable
    remote
    :remote-method="onRemoteSearch"
    clearable
    :multiple="multiple"
    :show-checkbox="multiple"
    :render-after-expand="false"
    :filter-node-method="filterNode"
    :props="{ value: 'id', label: 'label', children: 'children', disabled: 'disabled' }"
    style="width: 100%"
  >
    <template #default="{ data }">
      <el-tooltip v-if="!data.isGroup" :content="tip(data.raw)" placement="right" :show-after="200">
        <span>{{ data.label }}</span>
      </el-tooltip>
      <span v-else style="font-weight: 600; color: var(--ctms-text-muted)">
        {{ data.label }}
      </span>
    </template>
  </el-tree-select>
</template>
