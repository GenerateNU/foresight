import { formatEuro, formatSignedEuro } from '../../lib/format.js'
import ChangeBadge from './ChangeBadge.jsx'
import { daysOut, longDate, roundForDisplay } from './calendarUtils.js'

/**
 * The hover card: why this night costs what it does. DayCell decides when it shows and
 * where; `ref`, `style` and the rest of `props` come from Floating UI.
 */
export default function DayPopover({ rec, ref, style, ...props }) {
  const out = daysOut(rec.date)
  const factors = roundForDisplay(rec.rate, rec.baseline, rec.factors)

  return (
    <div
      ref={ref}
      style={style}
      className="z-20 w-80 rounded-card border border-stone-100 bg-white p-4 text-left shadow-xl"
      {...props}
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
          {factors.map((f) => (
            <li key={f.detail} className="flex justify-between gap-4">
              <span className="truncate">{f.detail}</span>
              <span className={f.sign > 0 ? 'text-price-up' : 'text-price-down'}>
                {formatSignedEuro(f.shown, f.sign)}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {rec.events.length > 0 && (
        <div className="mt-3 border-t border-stone-100 pt-3">
          <p className="mb-1 text-xs font-medium text-stone-600">Events in the city that night</p>
          <ul className="space-y-0.5 text-sm text-stone-700">
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
        </div>
      )}
    </div>
  )
}
