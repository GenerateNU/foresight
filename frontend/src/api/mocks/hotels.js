// Shape of HotelResponse (backend/foresight/routes/hotel.py).
export function mockHotel(id) {
  return {
    id,
    name: 'The Linden House',
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
    total_rooms: 24,
    latitude: 53.3389,
    longitude: -6.2591,
  }
}
