<script setup lang="ts">
/**
 * 打印前选人对话框（入库单/出库单打印入口）。
 *
 * 打印时签字位支持「系统账号预填」：这里列出该单据类型的签字位，每个位置一个
 * 账号下拉（可清空 = 不预填只留手写空间）；选中的账号若预存过签名图片，打印时
 * 直接嵌图（以图代签），否则印姓名 + 手写留白；「部门负责人」默认带出单据所属
 * 部门的负责人（组织架构指定过且可选时），取不到就留空。
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
  /** 点「打印」：signers 为 `{签字位: 账号 id}`（只含已选中的位置） */
  confirm: [signers: Record<string, number>]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const userOptions = ref<Dict[]>([])
/** orgId → 负责人账号 id（组织下拉附带 leader_user_id，登录即可取） */
const leaderByOrg = ref<Record<number, number>>({})

/** 展示用签字位（去重；V2.6.1 起两个部门负责人用 `#1/#2` 区分，各自独立选人） */
const uniqLabels = computed(() => [...new Set(props.labels || [])])

/** 内部键 → 显示文字（去掉 `#n` 后缀；与后端打印渲染同口径） */
function shownLabel(label: string): string {
  return String(label).split('#')[0]
}

/** 签字值 = 账号 id：打印接口按 id 回库取姓名，有签名图片则直接嵌图 */
const signers = reactive<Record<string, number | undefined>>({})

function resetSelection() {
  for (const key of Object.keys(signers)) delete signers[key]
  // 部门负责人默认选中：单据部门在组织架构里指定了负责人才带出，否则留空（手写）
  const deptLeader = props.orgId ? leaderByOrg.value[props.orgId] : undefined
  for (const label of uniqLabels.value) {
    // V2.6.1：`部门负责人#1` = 单据所属部门负责人（组织架构默认带出）；
    //          `部门负责人#2` = 另一部门负责人（手选，不预填）
    if (shownLabel(label) === '部门负责人' && label.endsWith('#1') && deptLeader) {
      signers[label] = deptLeader
    }
  }
}

watch(() => props.modelValue, (open) => {
  if (open) resetSelection()
})

async function loadOptions() {
  try {
    // 账号下拉只含启用账号（后端 user_options 口径）；选项值用账号 id —— 打印接口
    // 的 signers 收 user_id，后端回库取姓名并在有签名图片时直接嵌图；
    // has_signature 用来给有签名的账号加「（已签名）」标记
    userOptions.value = await fetchMasterOptions('user')
  } catch {
    userOptions.value = []
  }
  try {
    const orgs = await fetchMasterOptions('org')
    leaderByOrg.value = {}
    for (const o of orgs) {
      if (o.leader_user_id) leaderByOrg.value[Number(o.id)] = Number(o.leader_user_id)
    }
  } catch {
    leaderByOrg.value = {}
  }
}

loadOptions()

function onConfirm() {
  const picked: Record<string, number> = {}
  for (const [label, id] of Object.entries(signers)) {
    if (id) picked[label] = id
  }
  visible.value = false
  emit('confirm', picked)
}
</script>

<template>
  <el-dialog v-model="visible" title="选择签字人员" width="420px" append-to-body>
    <p class="tip">选中的签字位打印账号姓名并保留手写签名空间；预存过签名图片的账号
      （标注「已签名」）将直接嵌入签名图片；留空则只印签字位名称。</p>
    <el-form label-width="110px">
      <el-form-item v-for="label in uniqLabels" :key="label" :label="shownLabel(label)">
        <el-select v-model="signers[label]" clearable filterable placeholder="不预填（手写）"
                   style="width: 100%">
          <el-option v-for="u in userOptions" :key="u.id"
                     :label="u.has_signature ? `${u.name}（已签名）` : String(u.name)"
                     :value="Number(u.id)" />
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
