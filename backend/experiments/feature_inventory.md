# Feature inventory (ticket #139)

## Purpose

Working list of every feature we might add to the pricing model for ticket #139:
what we have now, what we could add, and what we know about each. The outcome
(what we kept and why) goes in a decision record in `docs/decisions/` when the
experiments are done.

## Baseline to beat

Calendar (`room_type`, `day_of_week`, `month`) plus Irish public holidays, hotel
1, 2022-2025.

- Year test (train 2022-2024, test 2025): MAE 18.66
- Rolling test (24 monthly windows): average MAE 19.51, spread 6.37
- A change smaller than that spread counts as noise, so a feature has to help in
  most months.

## Rules

- A feature must be known before the night it describes, because the model
  predicts a month ahead. Anything only known after the night is allowed only as
  a lagged value.
- Anything from PredictHQ is tested differently, because its history is only
  about 90 days.
- Features are built as they would be known 30 days before each night.
- Nights without a price are skipped (about 20 each December), and 2026 stays
  out of the tests.
- A feature more than 25% empty overall is dropped before LASSO. The rule was
  set before seeing any scores.
- Blank is not zero. Counts can be 0. Averages stay blank. For LASSO only,
  blanks are filled with the median plus a "was missing" flag. The EBM keeps
  blanks.
- Nights before the booking data is trustworthy are left out of screening.

## All features

Tags: **[in model]**, **[PHQ]** from PredictHQ, **[have data]**, **[no data]**,
**[idea]** (new, from asking "why would this hotel's rate change?").

### Calendar

1. `room_type` [in model]
2. `day_of_week` [in model]
3. `month` [in model]
4. `is_public_holiday` [in model] [PHQ]. The baseline uses a hardcoded version.
5. `is_school_holiday` [in model] [PHQ]
6. Weekend flag [have data]
7. Week of year [have data]
8. Days to or from a holiday [have data]
9. School terms, from a list we write ourselves [idea]
10. Long-weekend flag (a bank holiday on a Monday or Friday) [idea]
11. Day of month, or end-of-month payday weekends [idea]
12. Year, or a time trend [idea]. Tested as `year` in `covid_recovery.py`: no
    better than the baseline (see "COVID recovery" below).

### Events

13. `event_count` [in model] [PHQ]
14. `event_attendance` [in model] [PHQ]
15. `event_rank_max` [in model] [PHQ]
16. `event_accommodation_impact` [in model] [PHQ]
17. `big_event_count` [in model] [PHQ]
18. `nearest_big_event_km` [in model] [PHQ]
19. Big recurring events from a list we write, like concerts and sports finals
    [idea]

### Recent history

20. Rate over the last 4 weeks, same weekday [have data]
21. Rooms sold over the last 4 weeks, same weekday [have data]
22. Rate on the same night last year [have data]
23. Rooms sold on the same night last year [have data]
24. How fast rooms sold is changing week over week [idea]

### Bookings

25. Lead time [have data]
26. Length of stay [have data]
27. Market segment mix [have data]
28. Rate plan mix [have data]
29. Company or agent share [have data]
30. Booking pace [have data]. Tried before and worse in 11 of 12 runs, so it
    goes last.

### Cancellations

31. Cancellation rate [have data]
32. Cancellation lead time, meaning how late people cancel [have data]

### Outside the data

33. Weather [have data], but out of the model (decision 0055)

## Open questions

- Do recent-history features (last 4 weeks, same night last year) hide events,
  and so affect the events test? How should we order the tests?
- Which candidates do we test, and which do we skip?

- Why does the cancellation rate jump in 2024?
- Week over week. Leaning towards skipping it.

## Dropped (no data, or nothing to learn from)

Checked against the database and the source exports (`backend/data/2022-2025.csv`).

- Rooms blocked and waitlist: 0 on every night of 2022-2025 in the source
  exports, and empty in the database. The hotel doesn't use them.
- Rooms available: 107 on every night. A column that never changes tells the
  model nothing.
- Rooms out of service: not known 30 days ahead (Actual & Forecast stops at
  today, decision 0037), and the hotel sets it itself, often in quiet periods.
  The source exports have it on 215-263 nights a year, but the database copy is
  empty, so the occupancy weights count out-of-service rooms as unsold. Worth
  re-uploading for the weights, even though it isn't a feature.
- No-shows: no field in any report, and only known on the night itself.
- Competitor rates, flights, trains, inflation or tourism numbers: no source.

## Findings on empty values

Source: `feature_screening.ipynb`, hotel 1, priced nights 2022-2025.

- The booking features are 2.3% empty overall, all before 2022-02-03, where the
  booking data starts.
- The cancellation rate is 1.0 for every night before 2022-02-03, because the
  booking side is empty. The blank test did not catch this.
- It then falls from 0.68 (February 2022) to 0.36 (June 2022), so bookings made
  before the data starts are missing for about 5 months.
- Yearly average cancellation rate: 2022 0.47, 2023 0.45, 2024 0.58, 2025 0.59.
- `non_leisure_share`, `company_share` and `agent_share` pass the blank test but
  are nearly constant, so they need a variation check.
- The blank test checks presence, not correctness, so values need a check too.

## Booking features miss rooms that were cancelled later

`booking_features` in `feature_screening.ipynb` counts rows of the `bookings`
table. That table only holds bookings that were never cancelled: the backfill
export lists bookings still live on the day it was run (decision 0047), and
only 1 of about 86,000 cancelled refs is also in `bookings`. So the notebook's
"rooms on the books 30 days before" leaves out every room that was on the books
then but cancelled afterwards. Whether a booking will cancel is decided after
the 30-day point, so this uses information the model wouldn't have.

| Year | On the books 30 days out (rebuild) | Notebook count | Missed |
|------|------------------------------------|----------------|--------|
| 2022 | 63.1                               | 47.0           | 16.0   |
| 2023 | 69.8                               | 50.8           | 19.0   |
| 2024 | 76.3                               | 54.6           | 21.8   |
| 2025 | 75.2                               | 58.1           | 17.1   |

(Average rooms per night, nights from 2022-03-15.) Training would see about a
quarter fewer rooms than serving, which sees every live booking, cancelled
later or not.

How far to trust the rebuild: compared with the hotel's own rooms sold per
night, it matches 98% of nights in 2023 and 100% in 2024, and from January 2023
to September 2025 it is never more than 2 rooms off. It is short by about 20
rooms in January-March 2022 and patchy until October 2022 (bookings made before
the export starts), and it runs 7-60 rooms too high in October-December 2025
(cause not looked into). So the 2023 and 2024 rows of the table are solid, 2022
is not, and 2022 should stay out of any booking-feature screening. That also
answers the screening-start question: January 2023, by a rule (the first month
from which the rebuild matches rooms sold) instead of a hand-picked date. The missed rooms aren't noise either: after removing month and
weekday averages, they correlate 0.29 with the rate, so busy nights carry more
bookings that cancel later.

Counts can be fixed with `booking_curves` and `rooms_on` in
`services/domain/booking.py`, which add back rooms cancelled after the as-of
date. Mix features (rate plan, segment, breakfast, length of stay) can't be:
the Cancellations report has no rate plan or segment, so they are only ever
measured on bookings that weren't cancelled.

## COVID recovery

Source: `covid_recovery.py`. Jan-May 2022 rates are 74-95% of the same month
in 2023-2025. Every way of removing that dip (dropping, flagging, a recovery
ramp, down-weighting) made the baseline worse: dropping Jan-May 2022 adds
€1.39 ± 0.49 a month on the rolling test. The reason is that off-season rates
peaked in 2023 and have fallen since (January 106, 97, 91), and the low 2022
months happen to pull the model toward 2024-2025 levels. `year` as an input and
time-decay weights were no better than the baseline. 2022 stays in, untreated;
the real gap is the model not seeing the current price level, which the
recent-history features should test.

## Known data issues

- 2026 has only 12 nights per month, so it is left out of the tests.
- No priced nights around Christmas, about Dec 22-28 each year. Rooms sold is 0
  on all of them in the source exports, so the hotel looks closed. Still
  confirming with the TL.
- Booking data starts in February 2022, so early 2022 nights look more cancelled
  than they were.

## LASSO screen and 2025 confirmation

Source: `lasso_screen.py`. Hotel 1, January 2022 dropped from every arm.

- **Setup.** 31 candidates, each built as known 30 days before the night. LASSO
  on the rate left after the calendar (month, weekday, holiday, weekend by
  month), on priced nights 2023-2024, with 12 expanding folds (each month of
  2024). Then the EBM on 2025, which the screen never saw. Booking counts come
  from both tables and equal `booking_curves` on all 1,410 nights.
- **Dropped before the LASSO** (nearly constant): non-leisure share, company
  share, agent share.
- **Baseline with January 2022 dropped:** year test MAE 19.33 (18.66 with it in),
  2025 monthly MAE 19.24. Every arm below is compared with this.
- **LASSO.** 22 of 28 got zero weight. Six held weight in 9 or more of 12 folds
  with one sign, and they are also the first six to enter as the penalty
  loosens: `avg_lead_on_books` (+9.8 euros per SD), `rooms_on_books` (+3.8),
  `cancel_lead_time` (+1.6), `trend_years` (-4.1), `night_before_holiday` (+0.8),
  `rate_last_year` (+0.8). The fold-to-fold spread is about 7 euros, so the
  screen is noisy.
- **EBM on 2025, each alone** (monthly change in MAE, standard error, months
  better of 12): `avg_lead_on_books` -1.10 +- 0.77 (8), `night_before_holiday`
  -0.55 +- 0.27 (8), `rooms_on_books` -1.32 +- 1.05 (6), `cancel_lead_time`
  -0.83 +- 0.93 (7), `rate_last_year` +0.19 +- 0.85 (6), `trend_years` +8.90
  (breaks: the EBM can't extend a trend past its training years).
- **Kept by the rule set before the run:** `avg_lead_on_books` and
  `night_before_holiday` (together -1.21 +- 0.76, year test 17.97).
- **Follow-up, picked after seeing 2025:** all six minus `trend_years` gives
  -2.21 +- 1.16 (8 of 12 months), 2025 monthly MAE 17.03, year test 16.99. Year
  bias rises from +2.75 to +6.06 euros, so predictions lean higher.
- **Control:** a column that is blank before 2023 and carries nothing else makes
  the EBM worse (+0.72 +- 0.46), so the booking features don't win by marking 2022.
- **Limits.** One hotel, 12 test months, one 30-day horizon (the live model
  prices 0-90 days out). Mix features cover only rooms never cancelled.

## Next steps

1. Decide whether `avg_lead_on_books` and `night_before_holiday` go in the model,
   and write the decision record. Check them at the horizons the model serves.
2. Retest `rooms_on_books` and `cancel_lead_time` as 2026 data arrives.
3. Look into why the booking rebuild runs high in October-December 2025.
4. Add the hand-written list of big recurring events (inventory item 19); the
   PredictHQ event inputs still can't be tested with this much history.
