const ROOM_TYPES = [
  { id: 1, name: 'Double', base: 180 },
  { id: 2, name: 'Suite', base: 290 },
]

/** Each runs for three nights, on the 1st-3rd, 10th-12th, 19th-21st and 28th-30th. */
const EVENTS = [
  { event_id: 1, title: 'Dublin Theatre Festival', venue: 'Gaiety Theatre', category: 'festivals', expected_attendance: 8000 },
  { event_id: 2, title: 'Web Summit', venue: 'RDS Arena', category: 'conferences', expected_attendance: 70000 },
  { event_id: 3, title: 'Dublin Marathon', venue: null, category: 'sports', expected_attendance: 25000 },
]

/**
 * Made-up rates in the shape of RecommendationResponse (backend/foresight/routes/hotel.py),
 * one row per night per room type. Stable: the same night always gets the same price.
 */
export function mockRecommendations(hotelId, { start, end }) {
  const rows = []
  for (const date of eachNight(start, end)) {
    for (const room of ROOM_TYPES) rows.push(night(hotelId, room, date))
  }
  return rows
}

function night(hotelId, room, date) {
  const day = new Date(`${date}T00:00:00`)
  const weekend = day.getDay() === 5 || day.getDay() === 6
  const event = (day.getDate() - 1) % 9 < 3 ? EVENTS[day.getMonth() % EVENTS.length] : null

  const factors = [
    weekend && { detail: day.getDay() === 5 ? 'Friday' : 'Saturday', amount: 35 },
    event && { detail: event.title, amount: Math.round(room.base * 0.25) },
    { detail: 'Bookings so far', amount: (hash(date) % 41) - 20 },
  ].filter(Boolean)
  const rate = room.base + factors.reduce((sum, f) => sum + f.amount, 0)

  return {
    hotel_id: hotelId,
    stay_date: date,
    room_type: room.name,
    room_type_id: room.id,
    recommended_rate: money(rate),
    currency: 'EUR',
    explanation: {
      summary: `€${rate}, mostly because of ${factors[0].detail.toLowerCase()}`,
      baseline: money(room.base),
      factors: factors.map((f) => ({ detail: f.detail, amount: money(f.amount) })),
    },
    confidence_interval: { lower: money(rate * 0.9), upper: money(rate * 1.1), level: 0.8 },
    uncertainty: money(rate * 0.05),
    model_id: 1,
    model_version: 'ebm-v1',
    events: event ? [{ ...event, day_number: ((day.getDate() - 1) % 9) + 1, day_count: 3 }] : [],
    weather_source: 'forecast',
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
