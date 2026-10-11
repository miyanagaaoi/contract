<script setup lang="ts">
/**
 * 核销明细表（V2.5，AC-V2.5-04）。
 *
 * 付款单/收款单/发票靠它回答"这笔钱、这张票对应哪张单据"—— 没有核销关系就做不出
 * 按单据的进度列（`docs/28` §3.1）。M1 界面只允许**一行**（一付款单对一单据），
 * 但数据结构与校验都按多行实现：放开多单核销时只需去掉这里的行数限制。
 *
 * 目标单据下拉的候选由父页面传入（`options`），因为不同目标类型要走不同接口：
 * - 付款单 → 采购单、可选入库单；
 * - 收款单 → 销售订单、可选出库单；
 * - 发票 → 进项=采购单、销项=销售订单（方向由父页面收窄）。
 *
 * `readonly` 为真（查看已保存单据 / 无编辑权）时整表只读，便于详情态直接复用。
 */
import { computed } from 'vue'

import type { AllocationRow } from '@/types/doc'
import { fmtMoney } from '@/utils/format'
import type { Dict } from '@/api'

const props = withDefaults(defineProps<{
  modelValue: AllocationRow[]
  /** 允许的目标类型（label 用于下拉前缀） */
  targets: { code: string; label: string }[]
  /** 候选目标单据（已按目标类型过滤；父页面负责加载） */
  options: Dict[]
  readonly?: boolean
  /** 是否显示税额列（发票） */
  showTax?: boolean
  /** 单据金额（用于"未核销"提示）；0 表示不显示 */
  totalAmount?: number
  /** M1 只允许一行（放开多单时置 false） */
  singleRow?: boolean
}>(), {
  readonly: false,
  showTax: false,
  totalAmount: 0,
  singleRow: true,
})

const emit = defineEmits<{ 'update:modelValue': [rows: AllocationRow[]] }>()

const rows = computed({
  get: () => props.modelValue || [],
  set: (v) => emit('update:modelValue', v),
})

const allocated = computed(() => rows.value
  .reduce((sum, row) => sum + Number(row.amount || 0), 0))

/** 未核销 = 单据金额 − 核销合计（可为负 = 超额核销，BR-V2.5-03 允许但提示） */
const unallocated = computed(() => Number(props.totalAmount || 0) - allocated.value)

const canAdd = computed(() => !props.readonly
  && !(props.singleRow && rows.value.length >= 1))

function addRow(): void {
  if (!canAdd.value) return
  const target = props.targets[0]?.code || ''
  rows.value = [...rows.value, { target_type: target, target_id: null, amount: 0, tax_amount: 0 }]
}

function removeRow(index: number): void {
  const next = [...rows.value]
  next.splice(index, 1)
  rows.value = next
}

function onTargetTypeChange(row: AllocationRow): void {
  // 目标类型换了，原来的目标单据必然不属于新类型 —— 清掉免得提交时被后端按"方向不符"拒掉
  row.target_id = null
}

function optionsOf(targetType: string): Dict[] {
  return props.options.filter((o) => (o.target_type || o.doc_type || '') === targetType
    || !o.target_type)
}
</script>

<template>
  <div>
    <el-table :data="rows" size="small" border>
      <el-table-column label="核销目标" min-width="260">
        <template #default="{ row, $index }">
          <div class="target">
            <el-select v-if="targets.length > 1 && !readonly" v-model="row.target_type"
                       style="width: 130px" @change="onTargetTypeChange(row)">
              <el-option v-for="t in targets" :key="t.code" :label="t.label" :value="t.code" />
            </el-select>
            <span v-else-if="readonly" class="gray">
              {{ targets.find((t) => t.code === row.target_type)?.label || row.target_type }}
            </span>
            <el-select v-if="!readonly" v-model="row.target_id" filterable clearable
                       placeholder="选择单据" style="flex: 1">
              <el-option v-for="o in optionsOf(row.target_type)" :key="o.id"
                         :label="`${o.doc_no}（${fmtMoney(o.total_amount)}）`" :value="o.id" />
            </el-select>
            <span v-else>{{ row.target_no || `#${row.target_id}` }}</span>
            <span v-if="readonly" class="idx">第 {{ $index + 1 }} 行</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="核销金额" width="150">
        <template #default="{ row }">
          <el-input-number v-if="!readonly" v-model="row.amount" :min="0" :precision="2"
                           :controls="false" style="width: 100%" />
          <span v-else>{{ fmtMoney(row.amount) }}</span>
        </template>
      </el-table-column>
      <el-table-column v-if="showTax" label="其中税额" width="130">
        <template #default="{ row }">
          <el-input-number v-if="!readonly" v-model="row.tax_amount" :min="0" :precision="2"
                           :controls="false" style="width: 100%" />
          <span v-else>{{ fmtMoney(row.tax_amount) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="备注" min-width="140">
        <template #default="{ row }">
          <el-input v-if="!readonly" v-model="row.remark" placeholder="可选" />
          <span v-else>{{ row.remark || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column v-if="!readonly" label="操作" width="80">
        <template #default="{ $index }">
          <el-button link type="danger" size="small" @click="removeRow($index)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <span class="gray">尚未添加核销明细：不填则视为"预付款/暂未对应单据"，不影响目标单据进度</span>
      </template>
    </el-table>

    <div class="foot">
      <el-button v-if="!readonly && canAdd" size="small" @click="addRow">添加核销行</el-button>
      <span v-if="singleRow && !readonly" class="gray">本期一次只能核销一张单据</span>
      <span class="sum">核销合计：<b>{{ fmtMoney(allocated) }}</b></span>
      <span v-if="totalAmount" :class="['sum', unallocated < 0 ? 'over' : '']">
        未核销：<b>{{ fmtMoney(unallocated) }}</b>
        <template v-if="unallocated < 0">（已超额核销）</template>
      </span>
    </div>
  </div>
</template>

<style scoped>
.target { display: flex; align-items: center; gap: 8px; }
.idx { color: var(--ctms-text-muted); font-size: var(--ctms-fs-xs); }
.foot { display: flex; align-items: center; gap: 14px; margin-top: 8px; }
.sum { font-size: var(--ctms-fs-sm); }
.over { color: var(--ctms-danger-text); }
.gray { color: var(--ctms-text-muted); font-size: var(--ctms-fs-sm); }
</style>
