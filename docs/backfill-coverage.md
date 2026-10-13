# Backfill coverage

What the historical backfill (ticket 37) actually got, per source. Numbers are
from a local Docker Postgres run on 2026-10-12; re-run on Neon once it's set up.

Hotel data isn't loaded yet, so these runs used explicit `--start`/`--end`
instead of the hotel window. Once a hotel's nights are in `daily_performance`,
pass `--hotel-id` and leave the dates out: every script defaults to that
hotel's first → last `stay_date`.

## Summary

| Source | Market | Requested | Earliest usable | Rows | Known gaps |
|---|---|---|---|---|---|
| Weather (Open-Meteo) | Dublin | 2020-01-01 → 2026-10-11 | 2020-01-01 | 2,476 | none |
| Events (PredictHQ) | Dublin, 10 km | 2026-01-01 → 2026-10-11 | 2026-07-01 | 2,666 | everything before 2026-07-01 |
| Flights (AeroDataBox) | DUB | not run | — | — | no API key yet |

## Weather — Open-Meteo Historical API

- Recorded actuals (`is_forecast = false`), one row per city and day.
- The archive goes back to 1940, so it covers any hotel window.
- 2,476 of 2,476 days saved; no missing days and no days without values.
- Re-running the full range kept the count at 2,476 (zero duplicates).
- Requests are one year at a time, retrying 429/5xx/network errors (2s, 4s, 8s).
- Free tier is for non-commercial use; a commercial deployment needs a paid plan.

## Events — PredictHQ

- 2,666 events: 2,488 active, 178 that PredictHQ marked deleted (cancelled).
- **Trial floor: 2026-07-01.** Requesting from 2026-01-01 returned nothing
  before July, so the trial gives about 3½ months of history. Covering an
  older hotel window needs a paid plan.
- Re-running September: `new=0 unchanged=987` (zero duplicates).
- Monthly chunks, retries on 429/5xx with `Retry-After`, stops cleanly and
  prints where to resume if credits run out.

## Flights — AeroDataBox (via RapidAPI)

- **Not run: no `XRAPIDAPI_KEY` yet.**
- Each day costs about 4 API units; the free plan has 400 a month, so roughly
  100 days per month on the free tier.
- History floor not confirmed yet — check the RapidAPI plan and record it here.
- Retries 429/5xx (2s, 4s, 8s); a 429 after that is treated as the monthly
  quota, and the run stops with `resume with --start <day>`.

## Re-running

From `backend/`, with `DATABASE_URL` pointing at the target database:

    uv run python scripts/backfill/backfill_weather.py --hotel-id 1
    uv run python scripts/backfill/weather_coverage.py --city Dublin --hotel-id 1
    uv run python scripts/backfill/backfill_events.py --hotel-id 1
    uv run python scripts/backfill/backfill_flights.py --hotel-id 1 --airport DUB

Leave out `--start`/`--end` to use the hotel's window. Without a hotel, give
`--city --lat --lon` (weather, events) and both dates.

Events commit after each month and flights after each day, so a run stopped by
a quota keeps everything before it; re-run with the printed `--start`.
