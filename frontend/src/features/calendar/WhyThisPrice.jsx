import Card from '../../components/ui/Card.jsx'
import { formatEuro, formatSignedEuro } from '../../lib/format.js'
import { groupFactors, roundForDisplay } from './calendarUtils.js'

/**
 * Every factor behind the night's rate, grouped, in whole euros. The starting point plus
 * every line adds up to the rate shown, as on any breakdown (docs/decisions/0065).
 */
export default function WhyThisPrice({ rec }) {
  const { groups, leftover } = groupFactors(roundForDisplay(rec.rate, rec.baseline, rec.factors))

  return (
    <Card className="flex flex-col gap-4 shadow-sm">
      <div>
        <h2 className="text-lg font-medium">Why this price</h2>
        <p className="text-xs text-stone-500">What moved the rate, largest effect first in each group</p>
      </div>

      <Line label="Starting point" amount={formatEuro(rec.baseline)} muted />

      {groups.map((group) => (
        <section key={group.name} className="border-t border-stone-100 pt-3">
          <h3 className="mb-1 text-xs font-medium text-stone-600">{group.name}</h3>
          <ul className="space-y-1">
            {group.lines.map((line) => (
              <FactorLine key={line.detail} line={line} />
            ))}
          </ul>
        </section>
      ))}

      {leftover && (
        <ul className="border-t border-stone-100 pt-3">
          <FactorLine line={leftover} />
        </ul>
      )}

      <div className="border-t border-stone-200 pt-3">
        <Line label="Our rate, before VAT" amount={formatEuro(rec.rate)} strong />
      </div>
    </Card>
  )
}

function FactorLine({ line }) {
  return (
    <li className="flex justify-between gap-4 text-sm">
      <span>{line.detail}</span>
      <span className={`shrink-0 whitespace-nowrap ${line.sign > 0 ? 'text-price-up' : 'text-price-down'}`}>
        {formatSignedEuro(line.shown, line.sign)}
      </span>
    </li>
  )
}

function Line({ label, amount, muted = false, strong = false }) {
  return (
    <p className={`flex justify-between text-sm ${muted ? 'text-stone-500' : ''} ${strong ? 'font-medium' : ''}`}>
      <span>{label}</span>
      <span>{amount}</span>
    </p>
  )
}
