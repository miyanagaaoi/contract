const DIGITS = '零壹贰叁肆伍陆柒捌玖'
const UNITS = ['', '拾', '佰', '仟']
const BIG = ['', '万', '亿', '万亿']

function fourWords(num: number): string {
  let out = ''
  let zero = false
  for (let i = 3; i >= 0; i -= 1) {
    const digit = Math.floor(num / 10 ** i) % 10
    if (digit === 0) {
      if (out) zero = true
      continue
    }
    if (zero) { out += '零'; zero = false }
    out += DIGITS[digit] + UNITS[i]
  }
  return out
}

function intWords(yuan: number): string {
  if (yuan === 0) return '零'
  const chunks: number[] = []
  let n = yuan
  while (n > 0) { chunks.push(n % 10000); n = Math.floor(n / 10000) }
  const parts: string[] = []
  for (let idx = chunks.length - 1; idx >= 0; idx -= 1) {
    const chunk = chunks[idx]
    if (chunk === 0) {
      if (parts.length && chunks.slice(0, idx).some((v) => v > 0) && parts[parts.length - 1] !== '零') {
        parts.push('零')
      }
      continue
    }
    if (parts.length && chunk < 1000 && parts[parts.length - 1] !== '零') parts.push('零')
    parts.push(fourWords(chunk) + (BIG[idx] || ''))
  }
  return parts.join('')
}

/** 金额转人民币大写（与后端 amount_words 口径一致，用于前端预览） */
export function amountWords(amount: number): string {
  const value = Math.round((Number(amount) || 0) * 100) / 100
  if (value < 0) return `负${amountWords(-value)}`
  const yuan = Math.trunc(value)
  const cents = Math.round((value - yuan) * 100)
  const jiao = Math.floor(cents / 10)
  const fen = cents % 10
  let text = `${intWords(yuan)}元`
  if (jiao === 0 && fen === 0) return `${text}整`
  if (jiao) text += `${DIGITS[jiao]}角`
  else if (fen) text += '零'
  if (fen) text += `${DIGITS[fen]}分`
  return text
}
