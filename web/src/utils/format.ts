/**
 * 统一格式化工具（T0-2）。
 *
 * 收敛原先散落在 9 个文件里的 7 份重复实现（ContractsView / DashboardView /
 * DocListPage / MasterTablePage / DocItemsTable / RelatedDocs / purchase.OrderList /
 * sales.OrderList / BalanceView），并统一两条口径：
 *
 * 1. 金额与数量：`Intl.NumberFormat('zh-CN')`，千分位固定小数位。
 * 2. 空值与脏数据：一律渲染 `—`。
 *    原先 `DocItemsTable` 与 `ContractDetailDrawer` 输出 `'0.00'`，而
 *    `DocListPage` / `RelatedDocs` / `MasterTablePage` 输出 `'—'`，
 *    导致「空」与「零」在界面上不可辨；`RelatedDocs` 的孪生实现还漏了
 *    `Number.isNaN` 分支，脏数据会渲染出字面量 `NaN`。
 *
 * 日期说明：本文件的日期函数**不使用** `toISOString()`（那是 UTC），
 * 而是按本地时区读取年月日；输出仍保持后端 ISO 的 `YYYY-MM-DD` 形式，
 * 以免与导出 Excel、打印页的日期表现不一致。
 */

const PLACEHOLDER = '—'

const moneyFormatter = new Intl.NumberFormat('zh-CN', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const intFormatter = new Intl.NumberFormat('zh-CN', {
  maximumFractionDigits: 0,
})

/** 是否为空值（null / undefined / 空串） */
export function isBlank(v: unknown): boolean {
  return v === null || v === undefined || (typeof v === 'string' && v.trim() === '')
}

/** 安全转数字；空值或无法解析时返回 null（**注意：`0` 是合法值，不会被当成空**） */
export function toNumber(v: unknown): number | null {
  if (isBlank(v)) return null
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : null
}

/**
 * 数值口径说明（替换时必须按场景挑对应的函数，不要混用）：
 *
 * - **列表 / 统计 / 合计**：用千分位（`fmtMoney`、`fmtInt`）——便于比对量级。
 * - **行项录入表**：用无千分位（`fmtMoneyPlain`、`fmtQty`、`fmtPrice`）——
 *   列宽固定且需要逐格核对，千分位反而撑宽列、干扰读数。这是原
 *   `DocItemsTable` 用 `toFixed` 的有意选择，替换时不要一刀切。
 *
 * 两种口径的**空值表现统一为 `—`**（这是本次修复的核心）。
 */

const clampDecimals = (d: number): number => Math.max(0, Math.min(6, d))

/** 金额（列表/统计/合计）：千分位 + 2 位小数；空 → `—` */
export function fmtMoney(v: unknown): string {
  const n = toNumber(v)
  return n === null ? PLACEHOLDER : moneyFormatter.format(n)
}

/** 金额（行项录入表等窄列）：固定 2 位小数、**无千分位**；空 → `—` */
export function fmtMoneyPlain(v: unknown): string {
  const n = toNumber(v)
  return n === null ? PLACEHOLDER : n.toFixed(2)
}

/** 单价：固定位数小数、无千分位；空 → `—` */
export function fmtPrice(v: unknown, decimals = 2): string {
  const n = toNumber(v)
  return n === null ? PLACEHOLDER : n.toFixed(clampDecimals(decimals))
}

/** 数量：按物料单位小数位、无千分位；空 → `—` */
export function fmtQty(v: unknown, decimals = 2): string {
  const n = toNumber(v)
  return n === null ? PLACEHOLDER : n.toFixed(clampDecimals(decimals))
}

/** 整数（无小数位，千分位）；空 → `—` */
export function fmtInt(v: unknown): string {
  const n = toNumber(v)
  return n === null ? PLACEHOLDER : intFormatter.format(n)
}

/** 百分比：入参为 0–100 的数值；空 → `—` */
export function fmtPercent(v: unknown, decimals = 2): string {
  const n = toNumber(v)
  if (n === null) return PLACEHOLDER
  return `${new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: decimals,
  }).format(n)}%`
}

/**
 * 解析为 Date（本地时区）。
 *
 * 关键点：`new Date('2026-09-26')` 会被规范当作 **UTC 午夜**，在东八区之外
 * 会渲染成前一天。因此对无时区标记的 ISO 串显式按本地时间构造。
 */
function toDate(v: unknown): Date | null {
  if (v instanceof Date) return Number.isNaN(v.getTime()) ? null : v
  if (typeof v === 'number') {
    const d = new Date(v)
    return Number.isNaN(d.getTime()) ? null : d
  }
  if (isBlank(v)) return null
  const s = String(v).trim()
  const iso = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?/.exec(s)
  if (iso) {
    const [, y, mo, d, h = '00', mi = '00', sec = '00'] = iso
    return new Date(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(sec))
  }
  const parsed = new Date(s)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

const pad = (n: number): string => String(n).padStart(2, '0')

/** 日期：`YYYY-MM-DD`（本地时区）；空或不可解析 → `—` */
export function fmtDate(v: unknown): string {
  const d = toDate(v)
  if (!d) return PLACEHOLDER
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 日期时间：`YYYY-MM-DD HH:mm:ss`（本地时区）；空或不可解析 → `—` */
export function fmtDateTime(v: unknown): string {
  const d = toDate(v)
  if (!d) return PLACEHOLDER
  return `${fmtDate(d)} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** 时间：`HH:mm:ss`（本地时区）；空或不可解析 → `—` */
export function fmtTime(v: unknown): string {
  const d = toDate(v)
  if (!d) return PLACEHOLDER
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/**
 * 今天（本地时区），`YYYY-MM-DD`。
 *
 * ⚠️ 这是本次修复的一个既有缺陷：原实现用
 * `new Date().toISOString().slice(0, 10)` 取「今天」，取到的是 **UTC** 日期，
 * 东八区 00:00–08:00 期间会早一天，直接导致新建单据的默认日期错误。
 */
export function todayLocal(): string {
  return fmtDate(new Date())
}

/** 供 `el-table-column` 等需要 `—` 占位的场景复用 */
export const BLANK = PLACEHOLDER
