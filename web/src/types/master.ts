/**
 * 主数据页面配置类型（T-V2-15）。
 *
 * `<script setup>` 不允许 ES module 导出，因此通用组件与各页面共享的类型放在这里。
 */

export interface MasterField {
  prop: string
  label: string
  type?: 'input' | 'number' | 'textarea' | 'select' | 'switch' | 'options'
  required?: boolean
  span?: number
  /** type='options' 时，从 `GET /api/master/options/{optionKind}` 拉取候选 */
  optionKind?: string
  options?: { label: string; value: string | number }[]
  placeholder?: string
  precision?: number
  min?: number
  max?: number
  step?: number
  tip?: string
}

export interface MasterColumn {
  prop: string
  label: string
  width?: number
  minWidth?: number
  kind?: 'money' | 'tag' | 'status' | 'bool'
}

export interface ExtraFilter {
  prop: string
  label: string
  optionKind: string
}
