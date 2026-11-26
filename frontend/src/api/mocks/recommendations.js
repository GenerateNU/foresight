/** The real endpoint prices the one room type the active model prices. */
const ROOM_TYPE = { id: 1, name: 'DOUBLE', base: 180 }

/** Each runs for three nights, on the 1st-3rd, 10th-12th, 19th-21st and 28th-30th. */
const EVENTS = [
  { event_id: 1, title: 'Dublin Theatre Festival', venue: 'Gaiety Theatre', category: 'festivals', expected_attendance: 8000 },
  { event_id: 2, title: 'Web Summit', venue: 'RDS Arena', category: 'conferences', expected_attendance: 70000 },
  { event_id: 3, title: 'Dublin Marathon', venue: null, category: 'sports', expected_attendance: 25000 },
]

/**
 * Made-up rates in the shape of RecommendationResponse (backend/foresight/routes/hotel.py),
 * one row per night for one room type, in euros before VAT (decision 0076). Stable: the same night always gets the same price.
 */
export function mockRecommendations(hotelId, { start, end }) {
  return [...eachNight(start, end)].map((date) => night(hotelId, ROOM_TYPE, date))
}

const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]
/** What each weekday adds, roughly what the model learned for hotel 1. */
const DAY_AMOUNTS = [-12.4, -18.9, -15.2, -9.7, 4.6, 38.34, 31.8]

function night(hotelId, room, date) {
  const day = new Date(`${date}T00:00:00`)
  const event = (day.getDate() - 1) % 9 < 3 ? EVENTS[day.getMonth() % EVENTS.length] : null

  // Days from today to the night, 0 for today and past nights: the rate is what the night
  // would sell for if booked today (docs/decisions/0056).
  const leadDays = Math.max(0, Math.round((day - startOfToday()) / 86_400_000))

  // Shaped like backend/foresight/services/recommendations/explanation.py: one factor per model
  // input, named by the night's value, largest first, with the rest summed as "Smaller
  // effects combined". Events are only a count, and add about €0 for now (issue #128).
  const factors = [
    { detail: DAYS[day.getDay()], amount: DAY_AMOUNTS[day.getDay()] },
    { detail: MONTHS[day.getMonth()], amount: 6.63 },
    { detail: leadDays === 0 ? 'booking today' : `booking ${leadDays} days ahead`, amount: Math.round((4 - leadDays * 0.15) * 100) / 100 },
    event && { detail: 'event count 1', amount: 1.12 },
  ]
    .filter(Boolean)
    .sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount))
  const other = ((hash(date) % 300) - 150) / 100
  if (other) factors.push({ detail: 'Smaller effects combined', amount: other })
  const rate = room.base + factors.reduce((sum, f) => sum + f.amount, 0)
  const top = factors[0]

  return {
    hotel_id: hotelId,
    stay_date: date,
    room_type: room.name,
    room_type_id: room.id,
    lead_days: leadDays,
    recommended_rate: money(rate),
    explanation: {
      summary: `€${rate.toFixed(0)} from a typical €${room.base}; biggest factor: ${top.detail}: ${top.amount >= 0 ? '+' : '-'}€${Math.abs(top.amount).toFixed(2)}.`,
      baseline: money(room.base),
      factors: factors.map((f) => ({ detail: f.detail, amount: money(f.amount) })),
    },
    model_id: 1,
    events: event ? [{ ...event, day_number: ((day.getDate() - 1) % 9) + 1, day_count: 3 }] : [],
    events_source: 'fetched',
    // The manager has set their own rate on about one night in seven.
    manager_rate: hash(date) % 7 === 0 ? money(Math.round(rate / 5) * 5 + 10) : null,
    // Past nights aren't saved, so they have no snapshot to give feedback on.
    snapshot_id: day >= startOfToday() ? hash(date) % 100_000 : null,
    priced_at: new Date().toISOString(),
  }
}

/** Decimals arrive from the API as strings like "279.00". */
function money(amount) {
  return amount.toFixed(2)
}

function* eachNight(start, end) {
  const day = new Date(`${start}T00:00:00`)
  const last = new Date(`${end}T00:00:00`)
  while (day <= last) {
    yield `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`
    day.setDate(day.getDate() + 1)
  }
}

function startOfToday() {
  const now = new Date()
  return new Date(now.getFullYear(), now.getMonth(), now.getDate())
}

function hash(text) {
  let h = 0
  for (const char of text) h = (h * 31 + char.charCodeAt(0)) >>> 0
  return h
}
