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

/** 单条进度（V2.5）：分子/分母/百分比/是否超额。
 *
 * `pct === null` 表示分母为 0（界面显示 `—`，不是 `0%`）；百分比由**后端**算好
 * （`finance_service.progress_of`），前端只渲染，避免前后端两套算法漂移。
 */
export interface ProgressItem {
  num: number
  den: number
  pct: number | null
  over: boolean
}

/** 核销明细行（付款单 / 收款单 / 发票） */
export interface AllocationRow {
  target_type: string
  target_id: number | null
  target_no?: string | null
  amount: number
  tax_amount?: number
  remark?: string | null
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
  /** V2.3：仓库默认显示名（`主体码-仓库名`） */
  warehouse_display_name?: string | null
  /** V2.3：签约公司（我方主体码 / 名称快照） */
  subject_code?: string | null
  subject_name?: string | null
  /** V2.3：调拨单调出/调入单位（由两端仓库所属公司自动带出的快照） */
  from_subject_code?: string | null
  from_subject_name?: string | null
  to_subject_code?: string | null
  to_subject_name?: string | null
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
  /** 销售申请单特有：客户文本（未选客户档案时的兜底） */
  customer_name_text?: string | null
  sales_dept_id?: number | null
  expect_delivery_date?: string | null
  /** 销售订单特有：交期 / 收货信息 / 发运仓库 */
  delivery_date?: string | null
  delivery_address?: string | null
  contact_name?: string | null
  contact_phone?: string | null
  ship_warehouse_id?: number | null
  generated_in_id?: number | null
  generated_in_no?: string | null
  generated_out_id?: number | null
  generated_out_no?: string | null
  /** 同类单据的其它字段（如盘点单的 book_qty 汇总），保持宽松 */
  [key: string]: unknown
}

/** V2.5：财务单据与进度相关的附加字段（`[key: string]` 兜底之外的显式声明） */
export interface FinanceDocExtra {
  /** 采购单/销售订单：六条进度（键为 progressCols 里的字段名） */
  progress?: Record<string, ProgressItem>
  /** 财务单据：核销明细与已核销/未核销金额 */
  allocations?: AllocationRow[]
  allocated_amount?: number
  unallocated_amount?: number
  /** 付款/收款：结算方式与账户 */
  pay_account?: string | null
  recv_account?: string | null
  /** 采购/销售单据的回写金额 */
  paid_amount?: number
  received_amount?: number
  invoiced_amount?: number
  /** 发票特有 */
  invoice_direction?: string
  invoice_direction_label?: string
  invoice_code?: string | null
  invoice_no?: string
  invoice_type?: string | null
  invoice_date?: string | null
  tax_rate?: number | null
  amount?: number
  tax_amount?: number
  party_id?: number | null
  party_name?: string | null
  auth_status?: string
  auth_status_label?: string
  /** 列表行：是否超额核销 */
  over?: boolean
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
  /** V2.3：签约公司（我方主体码），如 ZC */
  subject_code?: string
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

/** 下推行（采购/销售申请→订单 / 订单→出入库单） */
export interface PushRow {
  src_item_id: number
  qty: number
  unit_price?: number
}

/** 盘点实盘录入行（`PUT /api/stock/takes/{id}/count`） */
export interface TakeCountInput {
  id: number
  actual_qty: number
  diff_reason?: string | null
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
  /** V2.3：仓库默认显示名（`主体码-仓库名`，如 ZC-主仓） */
  warehouse_display_name?: string | null
  /** V2.3：仓库所属公司（我方主体码 / 名称） */
  subject_code?: string | null
  subject_name?: string | null
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
