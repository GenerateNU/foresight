# 0017. Cities are the market every signal belongs to

**Status:** Accepted · **Date:** 2026-10-15

Supersedes [0010](0010-hotel-airport-codes.md).

## Context
Signals were matched to hotels by free-text city names, and different reads
compared them differently (one lower-cased, another compared exactly). Facts
about a place (timezone, airport, where to search) were copied onto each
hotel.

## Decision
- A `cities` table holds each market once: name, unique normalized slug,
  country, timezone, centre coordinates, and the IATA and ICAO airport codes.
- Hotels belong to a city. Weather, events, flight arrivals and competitor
  rates are stored against the city and shared by every hotel in it.
- Weather is read and events are searched at the city's centre. A hotel keeps
  its own coordinates for measuring distance to venues.

## Consequences
- Reads match on `city_id`. Spelling and case can no longer split a market.
- Two hotels in one city share one copy of each signal, so it is fetched once.
- A city with more than one airport, or a hotel outside its city's radius,
  would need this revisited.
