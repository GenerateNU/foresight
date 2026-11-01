import { formatEuro, formatSignedEuro } from '../../lib/format.js'
import ChangeBadge from './ChangeBadge.jsx'
import { daysOut, longDate } from './calendarUtils.js'

/**
 * The hover card: why this night costs what it does. Always in the DOM and shown by CSS
 * on hover or keyboard focus, so there's no hover state to manage. Keyboard focus only
 * (focus-visible): a mouse click also focuses the night, and would pin its card open.
 */
export default function DayPopover({ rec, className }) {
  const out = daysOut(rec.date)
  const topFactors = rec.factors.slice(0, 4)

  return (
    <div
      role="tooltip"
      className={`invisible absolute z-20 w-80 rounded-card border border-stone-100 bg-white p-4 text-left opacity-0 shadow-xl transition-opacity group-focus-visible:visible group-focus-visible:opacity-100 group-hover:visible group-hover:opacity-100 ${className}`}
    >
      <p className="text-base font-medium">{longDate(rec.date)}</p>
      <p className="text-xs text-stone-500">
        {out > 0 ? `${out} ${out === 1 ? 'day' : 'days'} out` : out === 0 ? 'Tonight' : 'In the past'}
      </p>

      <div className="mt-3 flex items-baseline gap-2">
        <span className="font-display text-3xl font-medium tracking-tight">{formatEuro(rec.rate)}</span>
        <ChangeBadge change={rec.change} />
      </div>
      <p className="text-xs text-stone-500">
        Likely range {formatEuro(rec.interval.lower)} to {formatEuro(rec.interval.upper)} (
        {Math.round(rec.interval.level * 100)}%)
      </p>

      <div className="mt-3 border-t border-stone-100 pt-3">
        <p className="mb-1 text-xs font-medium text-stone-600">What moved the rate</p>
        <ul className="space-y-1 text-sm">
          <li className="flex justify-between text-stone-500">
            <span>Starting point</span>
            <span>{formatEuro(rec.baseline)}</span>
          </li>
          {topFactors.map((f) => (
            <li key={f.detail} className="flex justify-between gap-4">
              <span className="truncate">{f.detail}</span>
              <span className={f.amount > 0 ? 'text-price-up' : f.amount < 0 ? 'text-price-down' : 'text-stone-500'}>
                {formatSignedEuro(f.amount)}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {rec.events.length > 0 && (
        <ul className="mt-3 space-y-0.5 border-t border-stone-100 pt-3 text-sm text-stone-700">
          {rec.events.slice(0, 3).map((e) => (
            <li key={e.id}>
              {e.title}
              {e.dayCount > 1 && (
                <span className="text-stone-500">
                  {' '}
                  (day {e.dayNumber} of {e.dayCount})
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
