const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]
const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

/** Column headings for the grid, Monday first. */
export const WEEKDAY_HEADERS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/** How many weeks the calendar shows, from Monday of this week. */
export const WEEKS = 5

/** "23 Nov to 27 Dec 2026", for the first and last night the grid shows. */
export function rangeLabel(firstIso, lastIso) {
  const short = (d) => `${d.getDate()} ${MONTHS[d.getMonth()].slice(0, 3)}`
  const first = new Date(`${firstIso}T00:00:00`)
  const last = new Date(`${lastIso}T00:00:00`)
  return `${short(first)} to ${short(last)} ${last.getFullYear()}`
}

/** "2026-10-17". Built by hand because Date#toISOString converts to UTC and can shift the day. */
export function toISODate(date) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** "Saturday 17 October". */
export function longDate(isoDate) {
  const d = new Date(`${isoDate}T00:00:00`)
  return `${WEEKDAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`
}

/** Whole days from today to `isoDate`; negative if it's in the past. */
export function daysOut(isoDate, today = new Date()) {
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const target = new Date(`${isoDate}T00:00:00`)
  return Math.round((target - start) / 86_400_000)
}

/**
 * `count` weeks from Monday of the week `today` is in, Monday first. Each week is 7
 * `{ date, label }`; `label` is the day of the month, with the month added on the 1st and
 * on the first day shown ("23 Nov", "24", ..., "1 Dec").
 */
export function buildWeeks(today, count = WEEKS) {
  const mondayOffset = (today.getDay() + 6) % 7 // getDay(): Sunday = 0
  const cursor = new Date(today.getFullYear(), today.getMonth(), today.getDate() - mondayOffset)

  const weeks = []
  for (let w = 0; w < count; w++) {
    const week = []
    for (let i = 0; i < 7; i++) {
      const first = (w === 0 && i === 0) || cursor.getDate() === 1
      week.push({
        date: toISODate(cursor),
        label: first ? `${cursor.getDate()} ${MONTHS[cursor.getMonth()].slice(0, 3)}` : String(cursor.getDate()),
      })
      cursor.setDate(cursor.getDate() + 1)
    }
    weeks.push(week)
  }
  return weeks
}

/** The recommendations keyed by night, for the grid to look each day up. */
export function ratesByNight(recommendations) {
  return new Map(recommendations.map((rec) => [rec.date, rec]))
}

/**
 * Which of 5 price buckets (1 cheapest .. 5 dearest) a rate falls in, relative to the nights shown.
 */
export function priceLevel(rate, min, max) {
  if (max === min) return 3
  return Math.min(5, 1 + Math.floor(((rate - min) / (max - min)) * 5))
}

const LEFTOVER_LINE = 'Smaller effects combined'
const MAX_FACTORS = 3

/**
 * The `max` largest factors, by size, with every other one added into "Smaller effects
 * combined", which comes last. The amounts still add up to the same total, so
 * roundForDisplay can run on the result. A real night can have 15 factors; the hover card
 * shows the top three, and night detail will show them all.
 */
export function capFactors(factors, max = MAX_FACTORS) {
  const named = factors
    .filter((f) => f.detail !== LEFTOVER_LINE)
    .sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount))
  const rest = [...named.slice(max), ...factors.filter((f) => f.detail === LEFTOVER_LINE)]
  if (rest.length === 0) return named
  const leftover = rest.reduce((total, f) => total + f.amount, 0)
  return [...named.slice(0, max), { detail: LEFTOVER_LINE, amount: leftover }]
}

/**
 * The factors in whole euros that add up to the rate the card shows (docs/decisions/0065).
 * Each amount is rounded; one under €1 counts as 0 and shows as "<€1". What rounding
 * leaves over goes to "Smaller effects combined", or the biggest factor if the API sent
 * none. Returns `{ detail, shown, sign }`: `shown` is whole euros, 0 meaning "<€1",
 * and `sign` is +1 or -1 for which way it moved the rate.
 */
export function roundForDisplay(rate, baseline, factors) {
  const lines = factors.map((f) => ({
    detail: f.detail,
    shown: Math.abs(f.amount) < 1 ? 0 : Math.round(f.amount),
    sign: f.amount < 0 ? -1 : 1,
  }))
  if (lines.length === 0) return lines

  const sum = lines.reduce((total, line) => total + line.shown, 0)
  const leftover = Math.round(rate) - Math.round(baseline) - sum
  const target = lines.find((line) => line.detail === LEFTOVER_LINE) ?? lines[0]
  target.shown += leftover
  if (target.shown !== 0) target.sign = Math.sign(target.shown)
  return lines
}
