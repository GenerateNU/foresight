# 0089. Services are grouped by feature

**Status:** Accepted · **Date:** 2026-11-25

## Context
`services/domain/` had grown to 18 files covering hotels, users, events,
bookings, training, tuning, recommendations and job freshness. `ingest/` and
`adapters/` then split the same features a second time, by role: the PredictHQ
client, its normalizer, the events ingest and the event rules sat in three
folders. `signals/` in the database and repository held one file each, left
from when weather was a second signal.

## Decision
- Services have one folder per feature, each holding that feature's outside
  source, ingest and rules:
  - `hotels/`: hotel, city
  - `users/`: user, access
  - `events/`: predicthq, normalize, window, ingest, event
  - `bookings/`: `guestline/` parsers, uploads, rows
  - `pricing/`: model, training_data, inputs, tuning, backtest
  - `recommendations/`: recommendation, explanation, feedback
  - `jobs/`: job, handlers, scheduler, freshness
  - `ml/` is unchanged: maths with no database.
- `ingest/bookings.py` was only wrappers around the two Guestline parsers; it
  is folded into `bookings/uploads.py`, and a report no longer carries an
  unused `extra` value or its own parse errors.
- Routes, repository and database models stay flat. `signals/` is removed, so
  events are `repository/event.py` and `database/models/event.py`.
- File names stay as they were where they still fit (`events/event.py`), so
  the `*_service` aliases keep matching.

## Consequences
- Most folders hold 2-5 files, and a feature's code is in one place.
- Moves and import changes only: no behaviour or schema change.
- Earlier decision records keep the paths they were written with.

## Addendum, 2026-11-25: experiments removed
`backend/experiments/` (the feature-screening notebook, lasso screen, baseline,
COVID-recovery and candidate scripts, and the feature inventory) is deleted.
Their findings are recorded in the decisions that used them (0051, 0055,
0067), and one script no longer ran. `just backtest` is how the model is
scored. `matplotlib`, used only by them, leaves the dev dependencies. Earlier
records that cite `experiments/` describe what was true then.
