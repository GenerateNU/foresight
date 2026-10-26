import { BASE, signed } from '../pricing'

const BAR_COLORS = { base: '#7D8590', up: '#6EA8FF', down: '#FF9A4D', total: '#E6EDF3' }

function PriceBreakdown({ factors, dayName, approved, onApprove }) {
  // Walk through the factors, keeping a running total, so each bar starts
  // where the previous one ended (a "waterfall" chart).
  const spans = []
  let total = 0
  for (const f of factors) {
    const start = f.kind === 'base' ? 0 : total
    total = f.kind === 'base' ? f.adj : total + f.adj
    spans.push({ ...f, start, end: total })
  }
  const price = total

  // Pick an axis that fits every bar with a little room on each side.
  const points = spans.map((s) => s.end).concat([BASE, price])
  const axisMin = Math.max(0, Math.floor((Math.min(...points) - 20) / 10) * 10)
  const axisMax = Math.ceil((Math.max(...points) + 20) / 10) * 10
  const range = axisMax - axisMin

  function barStyle(start, end, kind) {
    const lo = Math.max(Math.min(start, end), axisMin)
    const hi = Math.min(Math.max(start, end), axisMax)
    return {
      left: ((lo - axisMin) / range) * 100 + '%',
      width: Math.max(((hi - lo) / range) * 100, 1.2) + '%',
      background: BAR_COLORS[kind],
    }
  }

  const rows = spans.map((s) => ({
    label: s.label,
    kind: s.kind,
    value: s.kind === 'base' ? '$' + s.adj : signed(s.adj),
    bar: barStyle(s.kind === 'base' ? axisMin : s.start, s.end, s.kind),
  }))
  rows.push({ label: 'Price', kind: 'total', value: '$' + price, bar: barStyle(axisMin, price, 'total') })

  const sumText =
    spans.map((s, i) => (i === 0 ? String(s.adj) : (s.adj < 0 ? '− ' : '+ ') + Math.abs(s.adj))).join(' ') +
    ' = ' + price

  const delta = price - BASE
  const changeText = delta === 0 ? 'no change from $' + BASE : signed(delta) + ' vs $' + BASE
  const needsSignoff = Math.abs(delta) >= 150

  return (
    <section className="price-column">
      <div className="price-header">
        <div>
          <div className="price-for">Price for {dayName}</div>
          <div className="price-big">${price}</div>
        </div>
        <div className="price-change">{changeText}</div>
      </div>

      <div>
        {rows.map((row, i) => (
          <div key={i} className="waterfall-row">
            <span className={'waterfall-label' + (row.kind === 'base' || row.kind === 'total' ? ' strong' : '')}>
              {row.label}
            </span>
            <div className="waterfall-track">
              <div className="waterfall-bar" style={row.bar} />
            </div>
            <span className={'waterfall-value value-' + row.kind}>{row.value}</span>
          </div>
        ))}
      </div>
      <div className="waterfall-axis">
        <span />
        <div className="axis-labels">
          <span>${axisMin}</span>
          <span>${Math.round((axisMin + axisMax) / 2)}</span>
          <span>${axisMax}</span>
        </div>
        <span />
      </div>

      <div className="price-footer">
        <span className="sum">{sumText}</span>
        <div className="approve-area">
          {needsSignoff && <span className="signoff-badge">big change, needs sign-off</span>}
          <button className={approved ? 'approve approved' : 'approve'} onClick={onApprove}>
            {approved ? 'Approved ✓' : 'Approve $' + price}
          </button>
        </div>
      </div>
    </section>
  )
}

export default PriceBreakdown
