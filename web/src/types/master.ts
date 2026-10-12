/**
 * 主数据页面配置类型（T-V2-15）。
 *
 * `<script setup>` 不允许 ES module 导出，因此通用组件与各页面共享的类型放在这里。
 */

export interface MasterField {
  prop: string
  label: string
  type?: 'input' | 'number' | 'textarea' | 'select' | 'switch' | 'options' | 'tree-select' | 'subjects'
  required?: boolean
  span?: number
  /** type='options' 时，从 `GET /api/master/options/{optionKind}` 拉取候选 */
  optionKind?: string
  /**
   * V2.5+：`type='options'` 且 `storeText` 时，把选中项的**显示文本**写库（快照），
   * 而不是写 id。物料「品牌」用它存供应商**简称**：供应商改名/停用不影响历史物料。
   */
  storeText?: boolean
  /** `storeText` 时优先取候选对象的哪个字段作为文本（默认 name；品牌用 short_name） */
  textField?: string
  /**
   * V2.5+：**编辑已有记录时**该输入框只读。物料编码是审计线索，创建后不建议改；
   * 新增时仍可留空（留空自动生成）或显式指定（历史/导入场景）。
   */
  readonlyOnEdit?: boolean
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
