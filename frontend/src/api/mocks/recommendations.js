/** The real endpoint prices one room type, the hotel's first, unless `room_type_id` is given. */
const ROOM_TYPE = { id: 1, name: 'Double', base: 180 }

/** Each runs for three nights, on the 1st-3rd, 10th-12th, 19th-21st and 28th-30th. */
const EVENTS = [
  { event_id: 1, title: 'Dublin Theatre Festival', venue: 'Gaiety Theatre', category: 'festivals', expected_attendance: 8000 },
  { event_id: 2, title: 'Web Summit', venue: 'RDS Arena', category: 'conferences', expected_attendance: 70000 },
  { event_id: 3, title: 'Dublin Marathon', venue: null, category: 'sports', expected_attendance: 25000 },
]

/**
 * Made-up rates in the shape of RecommendationResponse (backend/foresight/routes/hotel.py),
 * one row per night for one room type. Stable: the same night always gets the same price.
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

  // Shaped like backend/foresight/services/domain/recommendation.py: one factor per model
  // input, named by the night's value, largest first, with the rest summed as "Smaller
  // effects combined". Events are only a count, and add about €0 for now (issue #128).
  const factors = [
    { detail: DAYS[day.getDay()], amount: DAY_AMOUNTS[day.getDay()] },
    { detail: MONTHS[day.getMonth()], amount: 6.63 },
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
    recommended_rate: money(rate),
    currency: 'EUR',
    explanation: {
      summary: `€${rate.toFixed(0)} from a typical €${room.base}; biggest factor: ${top.detail}: ${top.amount >= 0 ? '+' : '-'}€${Math.abs(top.amount).toFixed(2)}.`,
      baseline: money(room.base),
      factors: factors.map((f) => ({ detail: f.detail, amount: money(f.amount) })),
    },
    confidence_interval: { lower: money(rate * 0.9), upper: money(rate * 1.1), level: 0.8 },
    model_id: 1,
    model_version: 'ebm-v1',
    events: event ? [{ ...event, day_number: ((day.getDate() - 1) % 9) + 1, day_count: 3 }] : [],
    events_source: 'fetched',
    snapshot_id: null,
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

function hash(text) {
  let h = 0
  for (const char of text) h = (h * 31 + char.charCodeAt(0)) >>> 0
  return h
}
