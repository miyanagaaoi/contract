/**
 * V2.0 单据与库存相关类型（T-V2-24/25）。
 *
 * `<script setup>` 内不允许 `export interface`，因此单据页面共享的类型统一放在这里。
 * 字段与后端 `app/services/doc_service.fmt_doc` / `fmt_item` 的输出对齐。
 */

/** 单据行项（快照字段 + 下推进度字段） */
export interface DocItem {
  id: number
  seq: number
  product_id: number
  product_code: string
  product_name: string
  spec: string | null
  uom_name: string | null
  uom_decimals: number | null
  qty: number
  unit_price: number
  amount: number
  warehouse_id: number | null
  warehouse_name: string | null
  /** 下推来源行 id（列表/详情均可能为空） */
  src_item_id?: number | null
  ordered_qty?: number | null
  received_qty?: number | null
  shipped_qty?: number | null
  book_qty?: number | null
  actual_qty?: number | null
  diff_qty?: number | null
  diff_reason?: string | null
  remark: string | null
}

/** 通用单据（列表项不含 items，详情含 items） */
export interface DocRecord {
  id: number
  doc_type: string
  kind_label: string
  doc_no: string
  doc_date: string
  status: string
  status_label: string
  org_id: number | null
  created_by: number | null
  created_by_name: string | null
  handler_user_id: number | null
  contract_id: number | null
  contract_no: string | null
  source_doc_type: string | null
  source_doc_id: number | null
  source_doc_no: string | null
  submitted_at: string | null
  approved_at: string | null
  voided_at: string | null
  void_reason: string | null
  posted: boolean
  remark: string | null
  created_at: string | null
  updated_at: string | null
  total_amount: number
  editable: boolean
  items: DocItem[]
  // ---- 视单据类型附带 ----
  warehouse_id?: number | null
  warehouse_name?: string | null
  in_type?: string | null
  out_type?: string | null
  take_type?: string | null
  scope_note?: string | null
  supplier_id?: number | null
  supplier_name?: string | null
  customer_id?: number | null
  customer_name?: string | null
  currency?: string | null
  request_dept_id?: number | null
  need_date?: string | null
  purpose?: string | null
  suggest_supplier_id?: number | null
  purchase_dept_id?: number | null
  expected_arrival_date?: string | null
  settle_type?: string | null
  receipt_warehouse_id?: number | null
  generated_in_id?: number | null
  generated_in_no?: string | null
  generated_out_id?: number | null
  generated_out_no?: string | null
  /** 同类单据的其它字段（如盘点单的 book_qty 汇总），保持宽松 */
  [key: string]: unknown
}

/** 单据列表查询参数 */
export interface DocListQuery {
  keyword?: string
  status?: string
  date_from?: string
  date_to?: string
  include_voided?: boolean
  contract_id?: number | null
  warehouse_id?: number | null
  supplier_id?: number | null
  customer_id?: number | null
  handler_user_id?: number | null
  page?: number
  page_size?: number
}

/** 单据列表响应（含状态字典） */
export interface DocListResult {
  items: DocRecord[]
  total: number
  page: number
  page_size: number
  statuses: { code: string; label: string }[]
}

/** 单据保存负载（表头 + 行项） */
export interface DocSavePayload {
  doc_date: string | null
  remark: string | null
  contract_id: number | null
  handler_user_id: number | null
  items: {
    product_id: number
    qty: number
    unit_price?: number
    warehouse_id?: number | null
    remark?: string | null
  }[]
  /** 各单据类型的特有表头字段 */
  [key: string]: unknown
}

/** 下推行（采购申请→采购单 / 采购单→入库单） */
export interface PushRow {
  src_item_id: number
  qty: number
  unit_price?: number
}

/** 单据变更历史 */
export interface DocChangeLog {
  id?: number
  field_name: string
  old_value: string | null
  new_value: string | null
  note: string | null
  source: string | null
  operator_name: string | null
  created_at: string | null
}

/** 库存结存行 */
export interface StockBalance {
  product_id: number
  product_code: string | null
  product_name: string | null
  spec: string | null
  product_type_name: string | null
  uom_name: string | null
  uom_decimals: number | null
  warehouse_id: number
  warehouse_name: string | null
  qty: number
  safety_stock: number | null
  below_safety: boolean
  updated_at: string | null
}

/** 库存流水行 */
export interface StockLedgerRow {
  id: number
  biz_type: string | null
  doc_type: string | null
  doc_id: number | null
  doc_no: string | null
  src_doc_no: string | null
  qty_change: number
  qty_after: number
  unit_price: number | null
  created_by: number | null
  remark: string | null
  created_at: string | null
}

/** 库存流水响应（balance = 当前结存） */
export interface StockLedgerResult {
  items: StockLedgerRow[]
  total: number
  page: number
  page_size: number
  balance: number
}

/** 结存重算校验结果 */
export interface StockRecalcResult {
  checked: number
  consistent: boolean
  mismatch_count: number
  mismatches: { product_id?: number; warehouse_id?: number; qty?: number; ledger_qty?: number }[]
  fixed: boolean
}

/** 合同关联单据（后端 related-docs 未就绪时可能为 null） */
export interface ContractRelatedDoc {
  doc_type: string
  kind_label: string
  doc_no: string
  doc_date: string | null
  status: string
  status_label: string
  total_amount: number | null
  id: number
}

export interface ContractRelatedResult {
  docs: ContractRelatedDoc[]
  summary: Record<string, number>
}
