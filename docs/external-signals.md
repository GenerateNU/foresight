# External signals and hotel data

How each source reaches Postgres. Events have their own doc,
[event-extraction.md](event-extraction.md).

## The contract

An adapter produces normalized records. A repository upserts them. The caller
owns the transaction and commits once.

Repositories never commit. A multi-source run has to be all-or-nothing, and the
rolled-back-transaction fixture in `tests/conftest.py` is defeated by a
repository that commits internally.

| Source | Adapter | Repository | Table |
| --- | --- | --- | --- |
| Open-Meteo | `ingest/weather.py` | `repository/weather.py` | `weather` |
| OpenSky, AeroDataBox | `ingest/flights.py` | `repository/flights.py` | `flight_arrivals` |
| Client CSV | `services/parsers/hotel_data_parser.py` (CLI: `scripts/load_hotel_data.py`) | `repository/hotel.py` | `hotels`, `room_types`, `daily_performance` |
| PredictHQ, AskNews | `ingest/predicthq.py`, `ingest/asknews.py` | `repository/events.py` | `events`, `event_observations` |

Weather, flights, competitor rates and the hotel tables share `upsert_rows` in
`repository/__init__.py`, which upserts on a named constraint, touches a row
only when a value changed, and returns `{new, updated, unchanged}` counts.
Events keep their own upsert, because two sources describe the same event and
one has to win on precedence rather than last-write.

## Running them

External signals, one source per run:

```bash
cd backend
# Next 16 days of forecast
uv run python -m foresight.ingest.external --source weather \
    --city Dublin --lat 53.3498 --lon -6.2603
# Recorded actuals for a range, clamped to today
uv run python -m foresight.ingest.external --source weather \
    --city Dublin --lat 53.3498 --lon -6.2603 --start 2025-06-01 --end 2025-06-07
# Flights, needs credentials
uv run python -m foresight.ingest.external --source aerodatabox \
    --start 2026-10-05 --end 2026-10-11
```

Hotel booking history:

```bash
uv run python scripts/load_hotel_data.py \
    --input backend/data/<client>.csv --hotel-name "The Grand" \
    --city Dublin --base-rate 180.00 [--lat 53.3 --lon -6.2]
```

`--city` and `--base-rate` are required because the client export carries
neither. `total_rooms` is read from the export's `InStock` column. Coordinates
are optional and a run that omits them leaves any stored value alone, so the
events ingester's `--hotel-id` keeps working.

Re-running anything is safe. A second identical run reports every row
unchanged and writes nothing.

## Known gaps

- `flight_arrivals` is empty without an OpenSky client id and secret and a
  RapidAPI key. The code path is wired and tested.
- `daily_performance.rate` is the average rate paid (room revenue / rooms
  sold, the client's `ARR`), not the listed price, and is null on unsold nights.
  It is a stand-in until the client's listed-rate (BAR) history arrives.
- `competitor_rates` has a repository and tests but no adapter, so nothing
  populates it.
- Only one room type per hotel, named `Standard`. The client prices one
  standard room and applies its own multipliers downstream.
