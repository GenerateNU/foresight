import DayCell from './DayCell.jsx'
import { WEEKDAY_HEADERS, priceLevel } from './calendarUtils.js'

/** Lays the weeks out as a 7-column grid and hands each cell its night's recommendation. */
export default function WeekGrid({ weeks, byDate, mode }) {
  const rates = [...byDate.values()].map((r) => r.rate)
  const min = Math.min(...rates)
  const max = Math.max(...rates)

  return (
    <div>
      <div className="mb-2 grid grid-cols-7 gap-2 text-xs text-stone-500">
        {WEEKDAY_HEADERS.map((d) => (
          <span key={d}>{d}</span>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-2">
        {weeks.flatMap((week) =>
          week.map((day) => {
            const rec = byDate.get(day.date)
            const context = { priceLevel: rec ? priceLevel(rec.rate, min, max) : 1 }
            return (
              <DayCell
                key={day.date}
                day={day}
                rec={rec}
                mode={mode}
                context={context}
              />
            )
          }),
        )}
      </div>
    </div>
  )
}
