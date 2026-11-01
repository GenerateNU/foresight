import { apiGet } from './client.js'

/**
 * GET /hotels/{id}/recommendations?start=YYYY-MM-DD&end=YYYY-MM-DD (max 90 nights).
 * Returns one entry per night per room type; see docs/decisions/0038 in the repo.
 * The API sends money as strings ("279.00"), so they become numbers here, once.
 */
export async function getRecommendations(hotelId, { start, end }) {
  const rows = await apiGet(`/hotels/${hotelId}/recommendations`, { start, end })
  return rows.map(toRecommendation)
}

/** One API row in the shape the screens use: numbers for money, camelCase names. */
function toRecommendation(row) {
  const rate = Number(row.recommended_rate)
  // `previous_rate` isn't in the API yet (issue #96). Until it ships it's undefined,
  // so `change` is null and the calendar simply shows no up/down badge.
  const previous = row.previous_rate == null ? null : Number(row.previous_rate)

  return {
    date: row.stay_date,
    roomType: row.room_type,
    rate,
    change: previous == null ? null : rate - previous,
    interval: {
      lower: Number(row.confidence_interval.lower),
      upper: Number(row.confidence_interval.upper),
      level: row.confidence_interval.level,
    },
    summary: row.explanation.summary,
    baseline: Number(row.explanation.baseline),
    factors: row.explanation.factors.map((f) => ({
      detail: f.detail,
      amount: Number(f.amount),
    })),
    events: row.events.map((e) => ({
      id: e.event_id,
      title: e.title,
      dayNumber: e.day_number,
      dayCount: e.day_count,
    })),
    pricedAt: row.priced_at,
  }
}
