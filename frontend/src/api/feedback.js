import { apiPost } from './client.js'

/**
 * POST /hotels/{id}/feedback: the manager's own rate for a night, in euros before VAT.
 * `snapshotId` is the recommendation they saw. Each save adds a version; the latest one
 * comes back as `manager_rate` on the recommendations.
 */
export function saveManagerRate(hotelId, { date, rate, snapshotId }) {
  return apiPost(`/hotels/${hotelId}/feedback`, {
    stay_date: date,
    rate: rate.toFixed(2),
    snapshot_id: snapshotId,
  })
}
