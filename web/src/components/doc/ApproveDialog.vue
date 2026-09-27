<script setup lang="ts">
/**
 * 单据审核类动作弹窗（V2.0）：审核 / 驳回 / 作废 / 反审核 统一入口。
 *
 * - `mode` 决定标题、提示语与是否需要填写原因；
 * - 驳回 / 作废 / 反审核的原因**前端必填校验**（后端同样强制，422 由拦截器兜底提示）；
 * - 实际请求由父组件通过 `@confirm` 处理，本组件只负责交互与校验。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

export type ApproveMode = 'approve' | 'reject' | 'void' | 'unapprove'

const props = withDefaults(defineProps<{
  modelValue: boolean
  mode: ApproveMode
  /** 单据标题（如「采购申请单 CG…」），用于提示语 */
  subject?: string
  loading?: boolean
}>(), { subject: '该单据', loading: false })

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  confirm: [payload: { mode: ApproveMode; reason: string }]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const META: Record<ApproveMode, { title: string; tip: string; needReason: boolean; danger: boolean }> = {
  approve: { title: '审核通过', tip: '审核后单据将进入下一环节，库存类单据会同步过账。确定继续？', needReason: false, danger: false },
  reject: { title: '驳回', tip: '驳回后单据回到草稿状态，需填写驳回原因。', needReason: true, danger: false },
  void: { title: '作废', tip: '作废后单据不再参与后续业务，需填写作废原因。', needReason: true, danger: true },
  unapprove: { title: '反审核', tip: '反审核会撤销审核结果（库存类单据将红冲），需填写原因。', needReason: true, danger: true },
}

const meta = computed(() => META[props.mode])
const reason = ref('')

watch(() => props.modelValue, (v) => {
  if (v) reason.value = ''
})

function submit() {
  if (meta.value.needReason && !reason.value.trim()) {
    ElMessage.warning('请填写原因')
    return
  }
  emit('confirm', { mode: props.mode, reason: reason.value.trim() })
}
</script>

<template>
  <el-dialog v-model="visible" :title="meta.title" width="min(480px, 92vw)" append-to-body>
    <el-alert :title="meta.tip" :type="meta.danger ? 'warning' : 'info'" :closable="false" show-icon class="mb" />
    <div class="subject">目标单据：<b>{{ subject }}</b></div>
    <el-form label-width="80px" class="mt">
      <el-form-item :label="meta.needReason ? '原因' : '备注'" :required="meta.needReason">
        <el-input v-model="reason" type="textarea" :rows="3"
                  :placeholder="meta.needReason ? '必填，请说明原因' : '可选'"
                  maxlength="200" show-word-limit />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button :type="meta.danger ? 'danger' : 'primary'" :loading="loading" @click="submit">
        确定{{ meta.title }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.mb { margin-bottom: var(--ctms-gap); }
.mt { margin-top: 4px; }
.subject { font-size: var(--ctms-fs-sm); color: var(--ctms-text-secondary); }
</style>
