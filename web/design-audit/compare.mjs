/** 对比设计指标基线（report.baseline.json）与当前（report.json），用于批次出口判定。 */
import { readFileSync } from 'node:fs'

const read = (p) => JSON.parse(readFileSync(p, 'utf8'))
const base = read('D:/dsh/hetong/design-audit/report.baseline-batch2.json')
const now = read('D:/dsh/hetong/design-audit/report.json')

const keys = Object.keys(now.metrics)
const pad = (s, n) => String(s).padEnd(n)

console.log(pad('页面', 24), pad('字号档', 12), pad('小目标', 10), pad('ariaLabel', 12), '溢出')
for (const k of keys) {
  const b = base.metrics[k]
  const n = now.metrics[k]
  if (!b || !n) {
    console.log(pad(k, 24), '(新页面)')
    continue
  }
  const fontDiff = `${b.fontSizes.length} -> ${n.fontSizes.length}`
  const smallDiff = `${b.smallTargetCount} -> ${n.smallTargetCount}`
  const ariaDiff = `${b.ariaLabels} -> ${n.ariaLabels}`
  const ovf = `${b.overflowX} -> ${n.overflowX}`
  const flag = n.smallTargetCount > b.smallTargetCount || n.overflowX > b.overflowX ? '  <== 倒退' : ''
  console.log(pad(k, 24), pad(fontDiff, 12), pad(smallDiff, 10), pad(ariaDiff, 12), ovf + flag)
}

const regressed = keys.filter((k) => base.metrics[k]
  && (now.metrics[k].overflowX > base.metrics[k].overflowX
    || now.metrics[k].smallTargetCount > base.metrics[k].smallTargetCount))
console.log('\n运行时报错:', JSON.stringify(now.runtimeErrors))
console.log(regressed.length ? `存在倒退项: ${regressed.join(', ')}` : '无倒退项（overflowX 与小点击目标均未增加）')
