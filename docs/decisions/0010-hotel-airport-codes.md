# 0010. Hotels store both IATA and ICAO airport codes

**Status:** Accepted · **Date:** 2026-10-13

## Context
Flight arrivals are stored per airport, but nothing linked a hotel to its
airport. The flight sources disagree on codes: AeroDataBox uses IATA (`"DUB"`),
OpenSky uses ICAO (`"EIDW"`).

## Decision
Add `airport_iata` (`String(3)`) and `airport_icao` (`String(4)`) to `hotels`,
both nullable. One airport per hotel.

## Consequences
- Flight lookups match `flight_arrivals.airport` against either code.
- A hotel served by several airports would need a separate `hotel_airports`
  table; not needed for boutique hotels today.
