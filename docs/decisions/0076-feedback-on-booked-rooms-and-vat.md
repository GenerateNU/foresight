# 0076. Manager feedback on booked rooms, shown and taken with VAT

**Status:** Accepted · **Date:** 2026-11-19 · Amends [0069](0069-daily-tune-up.md),
[0070](0070-one-off-nights-teach-the-model-nothing.md),
[0071](0071-manager-rate-is-the-target-everywhere.md),
[0073](0073-how-the-backtest-judges-the-tune-up.md); reopens
[0075](0075-correction-ignores-month.md)

## Context
0068 to 0075 were written for a model that trained on one row per night.
[0056](0056-lead-days-input.md) changed that: a hotel with bookings and one
room type trains on one row per booked room per night, predicts `adr_nett` (the
rate before VAT) and reads `lead_days`. The feedback work had to fit that:
what a manager's rate is as a booked-room row, how much it counts, which price
the manager sees and types, and what the tune-up feeds the models.

## Decision
- **One kind of training row.** Booked rooms wherever the hotel trains on them
  (0056); night rows only for the hotels that fall back. Every piece of
  feedback below follows the hotel's rows.
- **A manager rate is a row of its own.** The calendar shows the price for
  booking the night *today*, so a manager's rate is the price for booking it
  on the day they saw the recommendation: a row for that night, booked that
  day (`shown_at` of the snapshot), with their rate. The night's real sales
  stay as they are. On night rows, the manager's rate replaces the night's
  (0071, unchanged).
- **It weighs 25% of the night's booked rooms, and at least 1**
  (`FeedbackSettings.manager_share`), so one rate isn't drowned out by the
  night's sales, and a future night with no bookings yet still counts. A
  starting value; there's no reliable test for a better one yet.
- **One-off nights lose their booked rooms too** (0070), not only their night
  row.
- **The model is nett; the manager sees and types listed prices.**
  `domain/prices` converts at the edges, in one place, at the country's VAT
  (`VAT_RATES`, 13.5% for Ireland; a city without a listed country gets
  Ireland's, like the holidays in 0067). On a version trained on booked rooms:
  - every price in a recommendation has VAT added: the rate, the interval, the
    uncertainty, the baseline and each factor, so the factors still add up;
  - `manager_rate` and the alignment gaps are shown the same way;
  - a rate the manager sends is taken back to nett before it's compared with
    the snapshot, stored or trained on.
  A version trained on nights (ARR) is shown and taken as it is. Everything
  stored stays nett, so a VAT change needs no recalculation.
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
- **The tuning backtest prices nights, not bookings.** The base trains on
  every row before the held-out days; each held-out night becomes one row at
  its average booked rate, booked the day before (`lead_days` 1). The manager
  prices nights, so that's what it replays.
- **The tune job goes through the hotel's queue** (0052), like every other job,
  so it never runs beside a train job for the same hotel.

## Consequences
- **The API changes what it returns.** Prices from a booked-room version are
  VAT-inclusive; `rate_basis` says which. Feedback `rate` is what the manager
  would list.
- **Feedback before this was empty on Neon**, so no stored rate needed
  converting.
- **A manager moves patterns, not single nights,** in a retrain: the model has
  no setting for one date, so a row shifts the effects it shares (its weekday,
  month, days ahead). The tune-up is where corrections land fast.
- **Nothing schedules the tune-up yet.** It runs when `POST /tune` is called;
  scheduling is a deployment task.
- **No reliable test yet** for the weight, the correction's inputs or the
  backtest's fixed one day ahead. Revisit them with a better testing setup.
