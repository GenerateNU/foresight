import { apiGet } from './client.js'

/** GET /hotels/{id}: `{ id, name, city: { name, ... }, total_rooms, ... }`. */
export function getHotel(hotelId) {
  return apiGet(`/hotels/${hotelId}`)
}
