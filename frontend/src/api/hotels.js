import { apiGet } from './client.js'

/** GET /hotels/{id}: `{ id, name, city: { name, ... }, ... }`. */
export function getHotel(hotelId) {
  return apiGet(`/hotels/${hotelId}`)
}
