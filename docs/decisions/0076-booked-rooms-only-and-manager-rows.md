# 0076. Train on booked rooms only; manager feedback as booked-room rows; prices before VAT

**Status:** Accepted, amended by [0079](0079-one-main-room-type-double-room-only.md) (one product, DOUBLE room only) · **Date:** 2026-11-19 · Supersedes [0003](0003-sample-weighting.md);
amends [0056](0056-lead-days-input.md), [0069](0069-daily-tune-up.md),
[0070](0070-one-off-nights-teach-the-model-nothing.md),
[0071](0071-manager-rate-is-the-target-everywhere.md),
[0073](0073-how-the-backtest-judges-the-tune-up.md); reopens
[0075](0075-correction-ignores-month.md)

## Context
0068 to 0075 were written for a model that trained on one row per night.
[0056](0056-lead-days-input.md) added a second path: a hotel with bookings and
one room type trains on one row per booked room per night and predicts
`adr_nett`, the rate before VAT; any other hotel still trained on nights and
predicted ARR. Two paths meant two targets, two weightings and two feedback
rules, and a question of which price the manager sees and types. We care about
individual booked rooms, so the night path goes.

## Decision
- **Training rows are booked rooms, from bookings alone.** One row per live
  booked room per night, target `adr_nett`, every input in `FEATURES`. The night
  path, its ARR target and its weights are gone. Training no longer reads
  Actual & Forecast: the window comes from the bookings, and a train job needs
  bookings and exactly one room type (Guestline's room codes don't map to room
  types yet).
- **Each booked room weighs 1. Occupancy weights are gone (supersedes 0003).** A
  night's rows are its rooms sold, so a half-full night already counts half as
  much as a full one; weighting each row by occupancy as well would count it
  twice. It only differs on nights with rooms out of service, or before the
  bookings export fully covers them. The training start is the caller's
  choice; a scheduled retrain will use everything.
- **A manager rate is a row of its own.** The calendar shows the price for
  booking the night *today*, so a manager's rate is the price for booking it
  on the day they saw the recommendation: a row for that night, booked that
  day (the snapshot's `created_at`), with their rate. The night's real sales
  stay as they are.
- **It weighs 25% of the night's booked rooms, and at least 1**
  (`FeedbackSettings.manager_share`), so one rate isn't drowned out by the
  night's sales, and a future night with no bookings yet still counts. A
  starting value; there's no reliable test for a better one yet.
- **One-off nights lose all their booked rooms** (0070).
- **Every price is before VAT, in and out.** The model learns `adr_nett`; the
  calendar shows it and the manager types their rate on the same basis, so
  nothing is converted. The frontend must say so where rates are shown and
  typed ("before VAT").
- **The tune-up builds its rows as serving does.** A manager's row is booked
  on the day their snapshot was shown; an untouched night on the day its latest
  snapshot was. It selects the base version's stored `features`, and the tuned
  version is saved with them, so serving gives it the same columns.
- **The correction sees every input the base does**, `lead_days` and `month`
  included: an edit made close to the night may mean something different from
  one made months ahead. 0075 measured that `month` made the correction learn
  a wrong seasonal effect (78% of runs beat the base with it, 45 of 45
  without); that is **open for the team to settle** once there's a testing
  setup the team trusts.
- **The backtests work on booked rooms.** The baselines predict a night from
  each training night's average booked rate and are scored against every booked
  room on the test night. The tuning backtest turns each held-out night into
  one row at its average booked rate, booked the day before (`lead_days` 1),
  because the manager prices nights.
- **The tune job goes through the hotel's queue** (0052), like every other job,
  so it never runs beside a train job for the same hotel.

## Consequences
- **Hotels with more than one room type can't train** until room codes map to
  room types (the main-room-type work), and a hotel with no bookings uploaded
  can't train at all.
- **Older versions keep serving as they are.** Serving uses each version's
  stored `features`; a version trained on nights before this still shows ARR,
  and `rate_basis` says so. Nothing is retrained.
- **Actual & Forecast is no longer read by training.** Removing its upload and
  table, and weather's, is a separate change.
- **Feedback was empty on Neon**, so no stored rate needed converting.
- **A manager moves patterns, not single nights,** in a retrain: the model has
  no setting for one date, so a row shifts the effects it shares (its weekday,
  month, days ahead). The tune-up is where corrections land fast.
- **Nothing schedules the tune-up yet.** It runs when `POST /tune` is called;
  scheduling is a deployment task.
- **No reliable test yet** for the manager weight, the correction's inputs or
  the tuning backtest's fixed one day ahead. Revisit them with a better testing
  setup.
