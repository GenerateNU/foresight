# 0086. Unread fields, the room-type routes and single-use abstractions are removed

**Status:** Accepted · **Date:** 2026-11-24 · Amends [0043](0043-manager-feedback-is-versioned.md),
[0068](0068-manager-sends-the-rate-they-chose.md), [0079](0079-one-main-room-type-double-room-only.md);
supersedes [0044](0044-train-on-feedback-given-after-the-night.md)'s record of
feedback used

## Context
After 0079 there's one room type, created by training, and after 0085 one fit.
Several things were still stored, carried or wrapped for cases that no longer
exist:

- **Stored, never read:** `pricing_model_feedback` (which manager rates each
  version learnt from), `feedback.verdict` and `feedback.timing`, and
  `recommendation_snapshots.model_version`. Each can be worked out from what's
  kept: the feedback table has every rate and when it was given, a version has
  its training window, the verdict is the manager's rate against the snapshot's,
  the timing is the stay date against `created_at`, and the version is the
  snapshot's `model_id`.
- **Carried, always the same:** a `room_type` column through training rows,
  the baselines, the backtest and its plots (always DOUBLE); the response's
  `currency` (always EUR).
- **Room-type routes:** `POST`/`GET /hotels/{id}/room-types` and
  `GET /room-types/{id}`. A room type made by hand can't be priced, and the
  frontend reads the room type from each recommendation.
- **Single-use abstractions:** an abstract `Model` base class with one
  subclass, a `FeedbackSettings` class wrapping one number, an always-empty
  `CORRECTION_EXCLUDED_INPUTS`, and `TrainingData.events_fetched` and
  `PreparedTraining.y`/`.weights`, set but never read separately.

## Decision
All of the above is removed. A migration drops the table and the three columns.
`MANAGER_SHARE = 0.25` is a constant in `pricing_model`; `score` moves into
`backtest`, its only user besides the experiments. A version's metrics still
count its `feedback_nights`.

## Consequences
- **Which rates a version learnt from** is: every current feedback rate for its
  room type with a stay date inside the version's training window (and, for a
  tune-up, every current rate at the time it was saved).
- **The feedback response no longer has `verdict` or `timing`.** A client can
  compare the rate with the recommendation it saw, and the stay date with the
  feedback's time.
- **Keeping `month` out of the correction (0075, open)** would add the exclusion
  back.
- Rolling back fills the columns again from what they were derived from; the
  table comes back empty.
