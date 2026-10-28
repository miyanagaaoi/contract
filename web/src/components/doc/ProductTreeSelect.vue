<script setup lang="ts">
/**
 * 物料树形选择器（V2.6.1 / CR-021、CR-025）：商品类型分组 → 物料。
 *
 * - 树形展开：按 `product_type_name` 分组，组节点不可选；
 * - 悬停浮窗（CR-025）：规格 / 单位 / 厂家 / 库存数量（全仓合计）；
 * - 草稿回显（CR-025 bug）：当前值不在已加载选项时（如草稿回填、物料超过首屏 50 条），
 *   用调用方传入的 `fallbackLabel` 合成一个叶子节点，避免显示成裸 id；
 * - 搜索：本地过滤 + 输入 ≥2 字远程补拉；
 * - 多选：`multiple`。
 */
import { computed, onMounted, ref } from 'vue'

import { fetchMasterOptions, http, type Dict } from '@/api'

const props = withDefaults(defineProps<{
  modelValue?: number | number[] | null
  placeholder?: string
  disabled?: boolean
  size?: 'small' | 'default' | 'large'
  multiple?: boolean
  /** 当前值的显示文案兜底（如 `名称（编码）`），用于草稿回显；值不在选项里时使用 */
  fallbackLabel?: string
}>(), {
  modelValue: null,
  placeholder: '按类型展开选择，或输入编码/名称搜索',
  disabled: false,
  size: 'small',
  multiple: false,
  fallbackLabel: '',
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: number | number[] | null): void
  (e: 'change', product: Dict | Dict[] | null): void
}>()

const products = ref<Dict[]>([])
const stockTotals = ref<Record<string, number>>({})
const loading = ref(false)
let remoteTimer: ReturnType<typeof setTimeout> | null = null

async function loadStockTotals() {
  const ids = products.value.map((p) => p.id as number)
  if (!ids.length) return
  try {
    const { data } = await http.get('/stock/product-totals', {
      params: { product_ids: ids.join(',') },
    })
    stockTotals.value = { ...stockTotals.value, ...(data as Record<string, number>) }
  } catch {
    // 无库存查看权限 / 网络问题：浮窗隐藏库存行即可
  }
}

async function load(keyword = '') {
  loading.value = true
  try {
    products.value = await fetchMasterOptions('product', keyword ? { keyword } : {})
    await loadStockTotals()
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

onMounted(() => load())

/** 当前值不在已加载选项中时，用 fallbackLabel 合成节点（草稿回显修复） */
const orphanLeaf = computed<Dict | null>(() => {
  if (props.multiple) return null
  const id = props.modelValue as number | null
  if (!id || products.value.some((p) => p.id === id) || !props.fallbackLabel) return null
  return { id, label: props.fallbackLabel, raw: { id, name: props.fallbackLabel }, orphan: true }
})

/** 产品类型分组 → 物料叶子节点 */
const treeData = computed<Dict[]>(() => {
  const groups = new Map<string, Dict[]>()
  for (const p of products.value) {
    const key = (p.product_type_name as string) || '未分类'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push({ id: p.id, label: `${p.name}（${p.code}）`, raw: p })
  }
  const tree = [...groups.entries()].map(([name, children]) => ({
    id: `t:${name}`, label: `${name}（${children.length}）`,
    disabled: true, isGroup: true, children,
  }))
  if (orphanLeaf.value) {
    tree.unshift({
      id: 't:__current__', label: '当前选择', disabled: true, isGroup: true,
      children: [orphanLeaf.value as Dict],
    })
  }
  return tree
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

function filterNode(query: string, data: Dict): boolean {
  const q = (query || '').trim().toLowerCase()
  if (!q) return true
  if (data.isGroup) {
    return (data.children || []).some((c: Dict) =>
      String(c.label || '').toLowerCase().includes(q))
  }
  return String(data.label || '').toLowerCase().includes(q)
}

function onRemoteSearch(query: string) {
  if (remoteTimer) clearTimeout(remoteTimer)
  const q = (query || '').trim()
  if (!q) { load(''); return }
  if (q.length < 2) return
  remoteTimer = setTimeout(() => { load(q) }, 250)
}

/** 浮窗内容（CR-025）：规格 / 单位 / 厂家 / 库存数量；无权限时省略库存 */
function tip(p: Dict | undefined): string {
  if (!p || p.orphan) return ''
  const parts = [
    `规格：${p.spec || '—'}`,
    `单位：${p.uom_name || '—'}`,
    `厂家：${p.brand || '—'}`,
  ]
  const qty = stockTotals.value[String(p.id)]
  if (qty !== undefined && qty !== null) parts.push(`库存：${qty}`)
  return parts.join(' ｜ ')
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
      <el-tooltip v-if="!data.isGroup && !data.orphan" :content="tip(data.raw)"
                  placement="right" :show-after="200">
        <span>{{ data.label }}</span>
      </el-tooltip>
      <span v-else-if="data.orphan">{{ data.label }}</span>
      <span v-else style="font-weight: 600; color: var(--ctms-text-muted)">
        {{ data.label }}
      </span>
    </template>
  </el-tree-select>
</template>
