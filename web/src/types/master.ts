/**
 * 主数据页面配置类型（T-V2-15）。
 *
 * `<script setup>` 不允许 ES module 导出，因此通用组件与各页面共享的类型放在这里。
 */

export interface MasterField {
  prop: string
  label: string
  type?: 'input' | 'number' | 'textarea' | 'select' | 'switch' | 'options' | 'tree-select'
  required?: boolean
  span?: number
  /** type='options' 时，从 `GET /api/master/options/{optionKind}` 拉取候选 */
  optionKind?: string
  /**
   * V2.1（N15）：字段右侧显示「快速新增」按钮，点击后弹窗新增对应主数据并自动回填。
   * 取值即要新增的种类（`product` / `product-type` / `uom`）。
   */
  quickCreate?: 'product' | 'product-type' | 'uom'
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
