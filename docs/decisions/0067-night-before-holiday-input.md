# 0067. The night before a public holiday is a model input, worked out from the date

**Status:** Accepted, amended by [0083](0083-holidays-from-the-library-only.md) (both holiday flags from the library) · **Date:** 2026-11-19

Adds an input to the list in [0055](0055-events-back-in-the-model.md) and to
[0007](0007-shared-feature-builder.md).

## Context
Ticket #139 screened 31 candidate inputs with a LASSO on 2023–2024, then added
the six it kept to the EBM one at a time and scored them on 2025, a year the
screen never saw. The rule for keeping an input was fixed before the run: lower
the average monthly error by more than its standard error, be better in at
least 7 of 12 months, and not raise the year-test error. Two inputs passed.
One is average lead time of booked rooms; [0056](0056-lead-days-input.md)
shipped a different form of it, days ahead per booked room. The other
is `night_before_holiday`.

Hotel 1, EBM, 2025:
- Against the baseline (calendar plus holidays), the monthly error fell by
  €0.55 ± 0.27, better in 8 of 12 months, and the year-test error went from
  €19.33 to €18.96 (`experiments/lasso_screen.py`).
- Rerun on the current model, events included, it fell from €19.51 to €19.07,
  also better in 8 of 12 months; the year-test error went from €19.71 to
  €19.28.

Measured again on the inputs as shipped (2025, the model without it against
with it, same nights): the year-test error fell from €19.71 to €19.01, the
monthly error by €0.74 ± 0.45, better in 9 of 12 months, and the year-test
bias went from +3.03 to +2.90. About two thirds of December's gain is one
night, 31 December 2025 (actual €207; €105 without the input, €218 with it),
which the experiment's list did not flag. Without December the monthly error
falls by €0.35 ± 0.24, better in 8 of 11 months, in line with the runs above.

The gain is small next to the noise (one hotel, 12 test months, a single month
can swing by more than €5). It is added because it passed a rule set before
the run, and it costs nothing to explain or serve.

The test built the input from a fixed list of Irish public holidays. It was not
built from PredictHQ's holiday records, which feed `is_public_holiday`: those
are empty on nights no events backfill covered (0041), and PredictHQ only
returns the last 90 days, so an input from them would be unknown on much of the
training history and would not be what was tested.

All of these numbers come from the model as it was before
[0056](0056-lead-days-input.md): one row per night, with ARR as the target.
Hotel 1 now trains on booked rooms with `adr_nett`, so the gain hasn't been
measured on the model it ships in.

## Decision
- **`night_before_holiday`** is 1 on a night when the next day is a day off for
  an Irish public holiday (the Sunday before a Monday bank holiday, 24
  December, 31 December) and 0 otherwise. It's an integer, like the other
  flags.
- **The holidays come from the [`holidays`](https://pypi.org/project/holidays/)
  library**, through `ml/holidays.days_off`, not from ingested data. It covers
  any year with nothing to maintain, and includes one-off holidays such as
  18 March 2022.
- **A holiday on a weekend also makes the next weekday off.** The library, like
  Irish law, keeps a weekend holiday on its own date, but most people get the
  next weekday off and banks close, which is what moves demand: Monday 18 March
  2024 for St Patrick's Day on a Sunday, Tuesday 27 December 2022 for Christmas
  on a Sunday. The day off is the next weekday that isn't already a holiday.
- **This differs from what #139 tested** on a few nights a year: the nights
  before those weekdays off, and 17 March 2022, before the one-off holiday. The
  experiment's hand-written list had neither.
- **Never unknown.** Unlike the event inputs it needs no data, so it is the
  same when training and when pricing a night 0 or 90 days out. That also
  means #139's one caveat, that it tested a single 30-day horizon, does not
  apply to it.
- **Its own group, `holidays`** in `INPUT_GROUPS`. Not `events`, which
  `--event-days` blanks on old nights. Not `calendar`, which is the baseline's
  inputs in the experiments and in `--inputs calendar`.
- **Ireland only.** A hotel in another country gets Ireland's holidays, which
  would be wrong for it. The country is one constant in `ml/holidays.py`; the
  city's `country` code can choose it once there's a second country.
- **Explained in words**: "the night before a public holiday", or "not the
  night before a public holiday".

Left out of the model: `rooms_on_books` and `cancel_lead_time` (better in 6
and 7 of 12 months, so not proven; retest as 2026 data arrives),
`rate_last_year` (no help), `trend_years` (the EBM cannot extend a trend past
the years it trained on; it added €8.9 a month in 2025) and the 22 that had no
weight in the LASSO.

## Consequences
- **Retrain to use it.** Serving gives each version only the inputs it stored
  ([0056](0056-lead-days-input.md)), so a version saved before this never sees
  the new column and keeps its prices. Once a new version is trained, every
  night is priced again once ([0038](0038-recommendations-reused-while-inputs-hold.md)).
- **Re-measure it on today's model.** The evidence above is from night rows and
  ARR. The test needs a window with several holidays in it, like #139's year
  test on 2025: a 30-night backtest from 13 September to 12 October has none,
  so it would show nothing.
- **The bias did not rise.** In #139 the year-test bias rose from +2.75 to
  +6.06 with the five-input set; with this input alone it went from +3.03 to
  +2.90.
- **Two holiday sources.** `is_public_holiday` still comes from PredictHQ and
  is empty where there's no event data; the library could replace it later.
- **The experiments see it, on today's training data.** The scripts in
  `backend/experiments/` read `training_data`, which for Hotel 1 is now booked
  rooms, not nights, so a rerun won't reproduce the numbers above.
  `baseline_testing.py` scores the current model, so it includes this input;
  its baseline does not, because that is built from `calendar`.
  `candidates.py` still lists it as a candidate. The scripts stay for now.
- No automated tests: the test suite was removed from `main`. The flagged
  nights were checked by hand for 2022 to 2027 (10 to 12 a year), including
  the weekday-off cases above.
