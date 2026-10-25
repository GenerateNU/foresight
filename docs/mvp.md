# Foresight MVP: user stories, action items, open questions

**Status:** Draft · **Date:** 2026-10-20

Use this document to plan and assign MVP work. Stories say what the MVP must
do, action items say what has to be built, and open questions list what is
still undecided. Designs are in [`designs/`](designs/).

## Scope

**Who:** the revenue manager of one boutique hotel in Dublin (a real client).

**Goal:** react within hours when something happens that moves demand,
especially events. The manager's own judgement always overrides the model, and
the model learns from it.

**The MVP is done when:** the manager logs in, uploads the day's PMS exports,
sees the next 30 nights on a calendar with recommended rates that reflect the
latest events, opens a night to see why it's priced that way, and sends
feedback that changes later recommendations. Everything is connected end to
end.

| In the MVP | Not in the MVP |
|---|---|
| One hotel, one login (data model ready for many hotels) | Multiple hotels per account |
| Events from PredictHQ | AskNews / news-extracted events |
| Weather | Flights, competitor rates (built but not connected) |
| Scheduled refresh and retraining | Pushing rates to the PMS or channel manager (no API exists) |
| Manual CSV upload of Guestline reports ([0032](decisions/0032-three-guestline-reports.md)) | Guestline API integration (full PMS access, but API needs partner onboarding) |
| One room type ("Standard") | Multiple room types (soon after) |

## User stories

The revenue manager is the only user in the MVP.

| # | As the revenue manager, I want to… | So that… | Acceptance |
|---|---|---|---|
| S1 | log in securely | the hotel's data isn't public | Email + password; every API route except `/health` needs a session |
| S2 | see recommended rates for the next 30 nights on a calendar | I can review the month at a glance | Matches [the calendar design](designs/); one rate per night from the active model |
| S3 | see how much each rate has changed since the last update | I spot what moved | Each card shows the change (e.g. ↑ €10) from the previous recommendation |
| S4 | see the events affecting each night | I know *why* demand is up | Card shows event names; the detail view lists event, venue and day (e.g. "day 2 of 3") |
| S5 | open a night and see why it's priced that way | I can trust or challenge it | Detail view shows the rate, its range and the factors in € (the EBM explanation) |
| S6 | see recommendations update within hours of a new event appearing | I can react to a crisis before competitors | Scheduled events refresh followed by new recommendations; time since last update is visible |
| S7 | tell the model a rate is too high, too low or right, and optionally enter the rate I'd charge, **before** the night | the model follows my judgement | Feedback saved per night; my rate is the one shown from then on |
| S8 | tell the model, **after** the night, what the rate should have been | it learns from outcomes | Same feedback form, on past nights |
| S9 | add a reason to my feedback (e.g. "wedding block", "venue sold out") | the system captures what I know that the data doesn't | Optional free text and/or tags, stored with the feedback |
| S10 | see my feedback reflected in later recommendations | I know it's being used | Feedback is used in the next retrain (on save or on schedule, see Q5) |
| S11 | upload my daily PMS CSV exports in the app | the model has the latest occupancy and sales | Upload screen with validation errors shown per file; job status visible until done |
| S12 | see when the data was last refreshed | I know if the rates are stale | Last successful events, weather, CSV and training times shown |

## Action items

Grouped by area so they can be assigned. **Bold** items block the end-to-end
MVP. Each item links to its stories.

### Backend: API and data

| # | Item | Stories |
|---|---|---|
| **B1** | **Auth: users table tied to a hotel, login/logout, protect all routes. New decision record superseding [0026](decisions/0026-no-authentication.md).** | S1 |
| **B2** | **Calendar endpoint: recommendations for a date range (`start`, `days=30`) in one call, instead of one call per night.** | S2 |
| **B3** | **Store recommendation snapshots per night per run (rate, interval, factors, model version, time) so the change since last time can be computed.** | S3, S6 |
| B4 | Events per night for the calendar (name, venue, day N of M), or include them in B2. | S4 |
| **B5** | **Feedback: table, migration and `POST/GET /hotels/{id}/feedback` (night, verdict, optional ideal rate, reason, before/after, model version seen). New decision record.** | S7, S8, S9 |
| B6 | Manager override: B2 returns the manager's rate when one exists, alongside the model's. | S7 |
| B7 | "Last updated" endpoint: latest successful job of each kind. | S12 |
| B8 | CORS and settings for the deployed frontend. | all |

### Backend: ML

| # | Item | Stories |
|---|---|---|
| **M1** | **Use feedback in training: decide how ideal rates and verdicts change labels or weights (see Q4), then implement. New decision record.** | S10 |
| M2 | Measure the time and cost of a retrain on the client's real data, to answer Q5. | S10 |
| M3 | Get events into the model (open question 1 in [system-design](system-design.md#10-open-questions)): PredictHQ history depth, backfill. This is the core value for S6. | S4, S6 |

### Backend: scheduling and operations

| # | Item | Stories |
|---|---|---|
| **O1** | **Scheduler: run events refresh, weather refresh, retraining and recommendation snapshots on a schedule (how: Q6; how often: Q7). Update [0020](decisions/0020-jobs-in-the-api-process.md) / system-design.** | S6 |
| O2 | Production deployment for the backend and frontend (where it's hosted, the domain, HTTPS). | all |
| O3 | Tests for the MVP flow (system-design open question 5). | all |

### Frontend

The current `frontend/` is a static prototype with no API calls.

| # | Item | Stories |
|---|---|---|
| **F1** | **App shell, API client, login screen (design exists).** | S1 |
| **F2** | **30-night calendar on B2 (design exists).** | S2, S3, S4 |
| **F3** | **Night detail view with rate, range, events and factors (popover design exists; "Open day" page not designed yet).** | S4, S5 |
| **F4** | **Feedback form in the night detail view (needs design).** | S7, S8, S9 |
| **F5** | **CSV upload screen with job progress (needs design).** | S11 |
| F6 | "Last updated" indicator. | S12 |

### Data and client

| # | Item | Stories |
|---|---|---|
| **D1** | **Collect the three Guestline exports in [guestline-data.md](guestline-data.md) (2 years, CSV, guest columns removed) and answer the "still to confirm" list in [0032](decisions/0032-three-guestline-reports.md).** | S11 |
| D2 | Booking-level table, parsers and migration for Daily New Reservations and Cancellations; map Blocks, ROOS and Wait List from Actual & Forecast. Check the rebuild of how full each night was against Actual & Forecast. New decision record. | S11, S2 |
| D3 | Weighting factors for "sold out too early" and waitlist, and "% sold so far" / "7-day pickup" features (Q2). New decision records. | S2, S10 |

## Open questions

| # | Question | Blocks |
|---|---|---|
| Q1 | How is the manager told about an update: a badge on the calendar card, a notification, or nothing beyond the change shown on the card? | F2, S6 |
| Q2 | **The design shows data the MVP doesn't have.** "% sold" and "Pickup, 7 days" can come from the Guestline booking reports ([0032](decisions/0032-three-guestline-reports.md), D2/D3). "Comp set median" and "Comp set gap" need competitor rates (out of scope): drop them or mock them? | D2, F2, F3 |
| Q3 | What goes on each calendar card and in the "Color by" options (Demand, Occupancy, Price change, Comp set gap, Events, Weather)? This is a design question. | F2 |
| Q4 | How does feedback train the model? Replace the label with the ideal rate, add a feature, or weight the night more? How are verdicts with no number used? Does "who was right" help the model? | M1 |
| Q5 | Retrain on every piece of feedback, or on a schedule? Depends on M2. | M1, O1 |
| Q6 | Where does the scheduler run: in the API process, external cron calling the API, or a Neon cron trigger? The API currently runs a single worker and jobs die on restart. | O1 |
| Q7 | How often should each refresh run (events, weather, retrain)? "Within hours" for events is the goal; PredictHQ credit limits apply. | O1, S6 |
| Q8 | ~~Which CSVs will the manager upload, and what decides whether a past rate was optimal?~~ Answered in [0032](decisions/0032-three-guestline-reports.md). Still open: which of the three the manager uploads daily vs. once as a backfill. | D1, D2 |
| Q9 | Auth: invite-only, or self-signup and Google login as in the design? The sign-up page says "free for 30 days" and "within the limits you set". Are trials and rate limits (min/max rates) in the MVP? | B1, F1 |
| Q10 | The design says "Rates shown are Double, lowest available". Until room types are added, is "Standard" the rate we show? | F2 |
| Q11 | Is past performance (e.g. the same night last year) ever shown? It's not in the MVP for now. | — |
