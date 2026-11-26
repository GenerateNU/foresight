import { parseAmount } from '../lib/format.js'
import { apiGet } from './client.js'

/**
 * GET /hotels/{id}/recommendations?start=YYYY-MM-DD&end=YYYY-MM-DD (max 90 nights).
 * Returns one entry per night, for the one room type the active model prices;
 * see docs/decisions/0079 in the repo.
 * Money arrives as strings ("279.00") and becomes numbers here, through parseAmount.
 */
export async function getRecommendations(hotelId, { start, end }) {
  const rows = await apiGet(`/hotels/${hotelId}/recommendations`, { start, end })
  return rows.map(toRecommendation)
}

/**
 * One API row in the shape the screens use: numbers for money, camelCase names.
 * Every amount is in euros, before VAT (decision 0076). `leadDays` is days from today: the
 * rate is what the night would sell for if booked today. `managerRate` is the manager's own
 * rate, or null.
 */
function toRecommendation(row) {
  const rate = parseAmount(row.recommended_rate)
  // `previous_rate` isn't in the API yet (issue #96). Until it ships it's undefined,
  // so `change` is null and the calendar simply shows no up/down badge.
  const previous = parseAmount(row.previous_rate)

  return {
    date: row.stay_date,
    roomType: row.room_type,
    rate,
    leadDays: row.lead_days,
    managerRate: parseAmount(row.manager_rate),
    change: previous == null ? null : rate - previous,
    summary: row.explanation.summary,
    baseline: parseAmount(row.explanation.baseline),
    factors: row.explanation.factors.map((f) => ({
      detail: f.detail,
      amount: parseAmount(f.amount),
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
