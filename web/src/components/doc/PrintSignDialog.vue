<script setup lang="ts">
/**
 * 打印前选人对话框（入库单/出库单打印入口）。
 *
 * 打印时签字位支持「系统账号预填 + 手写留白」：这里列出该单据类型的签字位，
 * 每个位置一个账号下拉（可清空 = 不预填只留手写空间）；「部门负责人」默认带出
 * 单据所属部门的负责人（组织架构指定过且可选时），取不到就留空。
 * 轻量实现：一个 el-dialog + 几个下拉 + 确认按钮，不做其它设计。
 */
import { computed, reactive, ref, watch } from 'vue'

import { fetchMasterOptions } from '@/api'
import type { Dict } from '@/api'

const props = defineProps<{
  /** v-model 可见性 */
  modelValue: boolean
  /** 签字位标签（重复标签只展示一个下拉，如两个「部门负责人」共用同一选择） */
  labels: string[]
  /** 单据所属组织节点 id（用于默认带出部门负责人；空则不做默认） */
  orgId?: number | null
}>()

const emit = defineEmits<{
  /** 点「打印」：signers 为 `{签字位: 姓名}`（只含已选中的位置） */
  confirm: [signers: Record<string, string>]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const userOptions = ref<Dict[]>([])
/** orgId → 负责人姓名（组织下拉附带 leader_name，登录即可取） */
const leaderByOrg = ref<Record<number, string>>({})

/** 展示用签字位（保持顺序去重：两个「部门负责人」共用一个下拉与一个预填） */
const uniqLabels = computed(() => [...new Set(props.labels || [])])

const signers = reactive<Record<string, string>>({})

function resetSelection() {
  for (const key of Object.keys(signers)) delete signers[key]
  // 部门负责人默认选中：单据部门在组织架构里指定了负责人才带出，否则留空（手写）
  const deptLeader = props.orgId ? leaderByOrg.value[props.orgId] : ''
  for (const label of uniqLabels.value) {
    if (label === '部门负责人' && deptLeader) signers[label] = deptLeader
  }
}

watch(() => props.modelValue, (open) => {
  if (open) resetSelection()
})

async function loadOptions() {
  try {
    // 账号下拉只含启用账号（后端 user_options 口径）；选项值用姓名 —— 打印接口
    // 的 signers 只收姓名文本，不解析用户 ID，避免后端为一次打印再反查
    userOptions.value = await fetchMasterOptions('user')
  } catch {
    userOptions.value = []
  }
  try {
    const orgs = await fetchMasterOptions('org')
    leaderByOrg.value = {}
    for (const o of orgs) {
      if (o.leader_name) leaderByOrg.value[Number(o.id)] = String(o.leader_name)
    }
  } catch {
    leaderByOrg.value = {}
  }
}

loadOptions()

function onConfirm() {
  const picked: Record<string, string> = {}
  for (const [label, name] of Object.entries(signers)) {
    if (name) picked[label] = name
  }
  visible.value = false
  emit('confirm', picked)
}
</script>

<template>
  <el-dialog v-model="visible" title="选择签字人员" width="420px" append-to-body>
    <p class="tip">选中的签字位将打印账号姓名并保留手写签名空间；留空则只印签字位名称。</p>
    <el-form label-width="110px">
      <el-form-item v-for="label in uniqLabels" :key="label" :label="label">
        <el-select v-model="signers[label]" clearable filterable placeholder="不预填（手写）"
                   style="width: 100%">
          <el-option v-for="u in userOptions" :key="u.id" :label="u.name" :value="u.name" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" @click="onConfirm">打印</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.tip { margin: 0 0 12px; color: var(--ctms-text-muted, #909399); font-size: var(--ctms-fs-sm, 12px); }
</style>
