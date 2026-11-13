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
12. Year, or a time trend, since rates may drift up over the years [idea]

### Events

13. `event_count` [in model] [PHQ]
14. `event_attendance` [in model] [PHQ]
15. `event_rank_max` [in model] [PHQ]
16. `event_accommodation_impact` [in model] [PHQ]
17. `big_event_count` [in model] [PHQ]
18. `nearest_big_event_km` [in model] [PHQ]
19. Big recurring events from a list we write, like concerts and sports finals
    [idea]

### Capacity

20. Rooms available [have data]
21. Rooms blocked [have data]
22. Rooms out of service [have data]
23. Waitlist [have data]

### Recent history

24. Rate over the last 4 weeks, same weekday [have data]
25. Rooms sold over the last 4 weeks, same weekday [have data]
26. Rate on the same night last year [have data]
27. Rooms sold on the same night last year [have data]
28. How fast rooms sold is changing week over week [idea]

### Bookings

29. Lead time [have data]
30. Length of stay [have data]
31. Market segment mix [have data]
32. Rate plan mix [have data]
33. Company or agent share [have data]
34. Booking pace [have data]. Tried before and worse in 11 of 12 runs, so it
    goes last.

### Cancellations

35. Cancellation rate [have data]
36. Cancellation lead time, meaning how late people cancel [have data]
37. No-shows [no field found yet]

### Outside the data

38. Weather [have data], but out of the model (decision 0055)
39. Competitor rates [no data]
40. Flights [no data]
41. Trains, meaning rail arrivals [no data]
42. Inflation or tourism numbers [idea, no data]

## Open questions

- Do recent-history features (last 4 weeks, same night last year) hide events,
  and so affect the events test? How should we order the tests?
- Which candidates do we test, and which do we skip?

## Known data issues

- 2026 has only 12 nights per month, so it is left out of the tests.
- No priced nights around Christmas, about Dec 22-28 each year. Cause unknown,
  and we are asking the TL.

## Next steps

1. Check coverage per source on Neon.
2. Decide which candidates to test.
3. Build their columns, then screen with LASSO on the rate left over after the
   calendar.
