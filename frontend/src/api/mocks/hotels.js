/** A made-up hotel in the shape of HotelResponse (backend/foresight/routes/hotel.py). */
export function mockHotel(id) {
  return {
    id,
    name: 'Beresford',
    city: {
      id: 1,
      name: 'Dublin',
      slug: 'dublin',
      country: 'IE',
      timezone: 'Europe/Dublin',
      latitude: 53.3498,
      longitude: -6.2603,
      airport_iata: 'DUB',
      airport_icao: 'EIDW',
    },
    latitude: 53.3389,
    longitude: -6.2591,
  }
}

/** A signed-in user in the shape of MeResponse (backend/foresight/routes/auth.py), with one hotel. */
export function mockMe() {
  return { id: 1, email: 'manager@example.com', name: 'Hotel Manager', hotels: [mockHotel(1)] }
}
