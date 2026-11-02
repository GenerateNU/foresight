const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]
const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

/** Column headings for the grid, Monday first. */
export const WEEKDAY_HEADERS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/** "October 2026". `month` counts from 0, like Date. */
export function monthLabel(year, month) {
  return `${MONTHS[month]} ${year}`
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
 * The weeks shown for a month, Monday first, padded with the neighbouring months' days.
 * Returns an array of weeks; each week is 7 `{ date, day, inMonth }`.
 */
export function buildMonthGrid(year, month) {
  const first = new Date(year, month, 1)
  const mondayOffset = (first.getDay() + 6) % 7 // getDay(): Sunday = 0
  const cursor = new Date(year, month, 1 - mondayOffset)

  const weeks = []
  do {
    const week = []
    for (let i = 0; i < 7; i++) {
      week.push({
        date: toISODate(cursor),
        day: cursor.getDate(),
        inMonth: cursor.getMonth() === month,
      })
      cursor.setDate(cursor.getDate() + 1)
    }
    weeks.push(week)
  } while (cursor.getMonth() === month)
  return weeks
}

/**
 * The API returns one row per night per room type. The calendar shows one number per
 * night, so keep the lowest rate (the Figma header says "lowest available").
 */
export function lowestRatePerNight(recommendations) {
  const byDate = new Map()
  for (const rec of recommendations) {
    const best = byDate.get(rec.date)
    if (!best || rec.rate < best.rate) byDate.set(rec.date, rec)
  }
  return byDate
}

/**
 * Which of 5 demand buckets (1 quiet .. 5 peak) a rate falls in, relative to the month.
 * Stand-in until real occupancy / pickup data exists: pricier night = busier night.
 */
export function demandLevel(rate, min, max) {
  if (max === min) return 3
  return Math.min(5, 1 + Math.floor(((rate - min) / (max - min)) * 5))
}
