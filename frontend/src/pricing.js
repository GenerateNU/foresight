// Example pricing numbers from the design mockup.
// These are hard-coded placeholders until the trained model is connected.

export const BASE = 150

export const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export const FULL_DAY = {
  Mon: 'Monday',
  Tue: 'Tuesday',
  Wed: 'Wednesday',
  Thu: 'Thursday',
  Fri: 'Friday',
  Sat: 'Saturday',
  Sun: 'Sunday',
}

export const DAY_ADJ = { Mon: -10, Tue: -10, Wed: -5, Thu: 0, Fri: 25, Sat: 40, Sun: 10 }

export const WEATHER = [
  { id: 'Clear', adj: 0, text: 'Clear skies' },
  { id: 'Cloudy', adj: -5, text: 'Cloudy' },
  { id: 'Rain', adj: -15, text: 'Rain in the forecast' },
  { id: 'Storm', adj: -25, text: 'Storm in the forecast' },
]

export const FLIGHTS = [
  { id: 'Fewer', adj: -20, text: 'Fewer flights landing' },
  { id: 'Normal', adj: 0, text: 'Normal flights' },
  { id: 'More', adj: 60, text: 'More flights landing' },
  { id: 'Surge', adj: 90, text: 'Flight surge' },
]

export const CATEGORIES = ['concert', 'sports', 'festival', 'conference']

const CATEGORY_WEIGHT = { concert: 1, sports: 0.8, festival: 0.6, conference: 0.5 }

// Formats an adjustment as "+$40", "−$15" or "$0".
export function signed(n) {
  if (n > 0) return '+$' + n
  if (n < 0) return '−$' + Math.abs(n)
  return '$0'
}

// How much one event adds to the price (a 65,000-person concert adds $120).
export function eventContribution(event) {
  const attendance = Math.max(0, Math.min(100000, Number(event.attendance) || 0))
  const weight = CATEGORY_WEIGHT[event.category] || 0.5
  return Math.round((weight * attendance) / 65000 * 120)
}

// Turns the current choices into the list of factors behind the price.
// Each factor has a label, its adjustment, and a kind: 'base', 'up' or 'down'.
export function priceFactors({ day, weather, flights, events }) {
  const factors = [{ label: 'Same as a normal weekend', adj: BASE, kind: 'base' }]

  const dayAdj = DAY_ADJ[day]
  if (dayAdj !== 0) {
    factors.push({ label: "It's a " + FULL_DAY[day], adj: dayAdj, kind: dayAdj > 0 ? 'up' : 'down' })
  }

  events
    .filter((e) => e.day === day)
    .forEach((e) => {
      const c = eventContribution(e)
      if (c !== 0) factors.push({ label: e.title, adj: c, kind: 'up' })
    })

  const f = FLIGHTS.find((x) => x.id === flights)
  if (f.adj !== 0) factors.push({ label: f.text, adj: f.adj, kind: f.adj > 0 ? 'up' : 'down' })

  const w = WEATHER.find((x) => x.id === weather)
  if (w.adj !== 0) factors.push({ label: w.text, adj: w.adj, kind: 'down' })

  return factors
}
