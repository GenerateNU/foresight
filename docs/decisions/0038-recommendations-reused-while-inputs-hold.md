# 0038. A recommendation is stored when made, and reused while its inputs hold

**Status:** Accepted · **Date:** 2026-10-27

Supersedes [0034](0034-snapshot-only-when-changed.md). Replaces the range
endpoint in [0032](0032-events-on-a-night-follow-the-model.md).

## Context
Under 0034, snapshots were saved by a separate run (`POST
/recommendations/snapshots`). `GET /recommendations` saved nothing, and
"unchanged" was judged on the output: the model ran every time, then its rate
and range were compared with the latest snapshot. A night's events came from
another endpoint, and a range of nights came from a third, which ran the model
once per night.

We want one endpoint that recommends a night or a range, stores what it
recommends, and only runs the model when something it reads has changed.

Timestamps can't say whether a night's inputs changed. An events refresh bumps
`last_seen_at` on every event it sees again, and a night without a forecast
uses its week's typical weather, which moves when any year's recorded weather
arrives and has no time of its own.

## Decision
- `GET /hotels/{id}/recommendations` takes `date` for one night, or `start`
  and `end` for a range of at most 90 nights. Sending both is a 422.
- For each night, the service loads its **inputs** from the database: the
  model's input row (from `build_features`), the events on the night (the rule
  in 0032), and where its weather came from. It then fingerprints them:
  SHA-256 of the active model's id and those inputs, as sorted JSON.
- Each night from today on:
  - **Matches its latest snapshot's fingerprint:** that snapshot is returned,
    and the model doesn't run.
  - **Differs, or has no snapshot yet:** the night is priced and stored as a
    new snapshot, with its inputs and fingerprint.
- Past nights are never stored after the fact. One with a snapshot returns its
  latest, as it was, even if its inputs changed since. One without is priced
  and returned with `snapshot_id: null`.
- The nights that need pricing are scored together, in one batch, and the
  model is only loaded if there is at least one.
- Each recommendation carries its night's factors, events and weather source,
  so there is no separate factors route: asking for one night again returns
  its stored snapshot without running the model while its inputs hold.
- Snapshots are still only added, never updated. A pricing model with
  snapshots still can't be deleted, and deleting a hotel still removes them
  (as in 0034).
- The night-events route, the range route and both snapshot routes are
  removed.

## Consequences
- `GET /recommendations` writes to the database. Calling it again with the
  same inputs writes nothing, so repeated calls are harmless.
- A snapshot's `created_at` is when its rate was last priced, not when it was
  last read.
- Anything the model starts reading (events, flights) is covered once it is in
  the input row; nothing else changes.
- Inputs that change and change back (A → B → A) store a row each time. That's
  why the fingerprint isn't unique per night.
- Two requests at the same moment could both store the same new snapshot. It's
  harmless and rare, so nothing prevents it.
- Snapshots stored before this decision have empty inputs and an empty
  fingerprint, so the first request for each of those nights stores one fresh
  row.
- The response changed from one object to a list, even for one night.
- The change since a night's previous snapshot isn't returned yet. Each
  snapshot keeps its inputs, so it can be added without a migration.
