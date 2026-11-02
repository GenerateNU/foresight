import ChangeBadge from './ChangeBadge.jsx'
import { formatEuro } from '../../lib/format.js'
import DayPopover from './DayPopover.jsx'
import { nightStyle } from './colorModes.js'

/**
 * One night in the grid. `rec` is undefined for days outside the month or with no price.
 * `row` / `col` only decide which way the hover card opens so it never leaves the screen.
 */
export default function DayCell({ day, rec, mode, context, row, col }) {
  if (!day.inMonth || !rec) {
    return (
      <div className="min-h-28 rounded-card border border-stone-100 bg-stone-25 p-3 text-stone-300">
        {day.day}
      </div>
    )
  }

  const { bg, dot } = nightStyle(mode, rec, context)
  const popoverPosition = [
    row >= 2 ? 'bottom-full mb-2' : 'top-full mt-2',
    col <= 1 ? 'left-0' : col >= 5 ? 'right-0' : 'left-1/2 -translate-x-1/2',
  ].join(' ')

  return (
    <div
      tabIndex={0}
      className={`group relative min-h-28 rounded-card border border-stone-100 p-3 outline-none focus-visible:ring-2 focus-visible:ring-sky-400 ${bg}`}
    >
      <div className="flex items-center justify-between text-sm">
        <span className="flex items-center gap-1.5">
          {day.day}
          <span className={`size-1.5 rounded-full ${dot}`} />
        </span>
        <ChangeBadge change={rec.change} />
      </div>
      <p className="mt-1 text-xl font-medium">{formatEuro(rec.rate)}</p>
      {rec.events[0] && (
        <p className="mt-2 truncate rounded-sm bg-white px-2 py-0.5 text-xs text-stone-700">
          {rec.events[0].title}
        </p>
      )}
      <DayPopover rec={rec} className={popoverPosition} />
    </div>
  )
}
