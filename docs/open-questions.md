# Open questions

Questions the team hasn't settled yet. Once one is decided, record it in
[`decisions/`](decisions/README.md) and remove it from this list.

## Model

### Should training use nights that haven't happened yet?

Training reads every booked night up to the last one booked, which can be
months ahead. Those nights are only partly sold, and some have a manager rate.
The backtest, by contrast, stops at yesterday.

The case for keeping them: there's no ground truth to check against. The model
is trying to get as close to the manager as it can, so more data, including
future bookings and future manager rates, should help.

The case against: a future night's early bookings may not reflect its final
price.

Not settled; keep using the future nights for now.

### Should old manager rates expire or count less?

Feedback is never cleared. Every retrain reads the current rate for each
night in its window, and every tune-up reads the current rate for every night
the manager has ever priced, with no date limit. A rate set a year ago counts
as much as one set yesterday.

A manager rate is a full price ("this night should be €165"), not a change to
what they were shown, so it stays a valid target whichever model was serving
when they set it. But if the manager's pricing changes over time, the old
rates keep pulling the model toward how they used to price.

Options: no limit (as now), an age limit (e.g. the last 90 or 365 days), or
weighting older rates less. Each could apply to retrains, tune-ups or both.

Not settled; every rate counts the same for now.

### Does a night left alone mean the manager agreed with it?

The tune-up learns every past night in the last 30 days that has a snapshot,
no manager rate and no one-off tag as "the manager accepted this price"
(decisions 0072, 0074, 0078). A snapshot only says the price was shown, not
that the manager looked at it.

The calendar fetches a whole month at once, so opening it once saves a
snapshot for every future night on screen. A manager who changes two
Saturdays and ignores the rest of the month leaves around 28 nights that
later count as accepted. Those nights pull the correction toward "keep the
shown price" and dilute what the manager did change: 4 Saturdays raised by
€15 and 6 left alone teach about +€6, not +€15. Before decision 0084 the
price job made this worse, by giving every night a snapshot whether or not
anyone opened the calendar.

Options:

- **Accept it** (as now): on screen and not changed counts as agreed.
- **Record what the manager reviewed**, e.g. a night counts only if its
  details were opened or the manager pressed "accept". Most accurate; needs a
  frontend change and somewhere to store it.
- **Weigh untouched nights less** than manager rates. Simple, but the weight
  is a guess until there's a test the team trusts.
- **Only count untouched nights from weeks the manager gave any feedback**,
  as a sign they were reviewing.

Not settled; on screen and not changed counts as agreed for now.

### Can a night left alone in the app disagree with Guestline?

**Priority: low.**

Untouched nights (decision 0072) are to learn from the rate the manager was
shown, since the goal is to match the manager. But the manager also sets
prices in Guestline. If they raise Tuesdays to €130 there and leave our €120
Tuesdays alone in the app:

- the imported bookings move the next retrain's base toward €130;
- the untouched Tuesdays still say €120, so the tune-up learns −€10 and the
  served price stays at €120.

Importing Guestline data keeps the base current; the question is only whether
the tune-up then pulls it back. It matters less if the manager sets prices in
our app, or if training uses only the bookings on the plan the manager prices
(e.g. `BAR_RO_DB` for DOUBLE), so sales and manager rates mean the same price.

To settle: where the manager sets prices (Guestline, our app, or both), and
whether training should keep only the manager's plan.

### Who starts retrains and tune-ups?

A manager rate saved on the night page shows on the calendar straight away,
but the model only learns from it when a retrain or tune-up runs, and nothing
starts either one today:

- `SCHEDULED_TRAINING` is off, so the daily routine only refreshes events.
- Decision 0069's daily tune-up was to come from a cron outside the app.
  Nothing in `render.yaml` or the repo calls `POST /hotels/{id}/tune`.
- A tune-up skips itself below 5 manager rates.

Options:

- **Manual** (as now): someone calls `POST /hotels/{id}/train` or `/tune`.
- **Turn on `SCHEDULED_TRAINING`**: a full retrain every day, which adds
  manager rates as training rows (decision 0076).
- **Add the tune-up to the scheduler**, so it runs daily inside the app
  rather than from an outside cron.
- **Both**: a tune-up every day, a full retrain less often.

Not settled; nothing retrains on its own for now.

### Does saving the rate we showed count as feedback?

The night page's "Your rate" field starts at our rate. A manager who presses
Save without changing it records a manager rate equal to the recommendation,
and the next retrain and tune-up learn from it. That trains the model on its
own output, the risk decision 0044 named. It may also be a real signal ("I
checked, this is right"), close to what the question on untouched nights
above is after.

Options:

- **Keep it** (as now): an unchanged save means the manager agreed.
- **Start the field empty, or disable Save until the rate changes.**
- **Store an unchanged save as "accepted"**, not as a rate, so it can be
  weighed separately.

Not settled; an unchanged save counts as a manager rate for now.

## Serving

### How fast does the calendar need to load?

Measured on hotel 1 from a laptop against Neon: a month that needs pricing
took 11 to 20 s, and one already priced that day took about 4 s. The time
goes to:

- **Loading the model.** Every request that prices any night fetches the
  7.7 MB artifact from Postgres (about 3.7 s); turning it into a model takes
  0.01 s. Nothing keeps it in memory between requests.
- **Building the inputs.** 1 to 5 s, done before checking which snapshots can
  be reused, so it's paid even when nothing is priced.
- **Prices reused only within a day.** Days booked ahead is an input, so a
  future night is priced again the first time it's shown each day (decision
  0084). A past night with no snapshot is priced on every request.

Decision 0084's "0.1 s to price 90 nights" counts scoring only. A server next
to Neon would fetch the model faster, but would still fetch it every time.

Options:

- **Keep loaded models in memory, by id.** A version never changes, so the
  copy can't go stale. A small change in `services/pricing/model.py`.
- **Speed up building the inputs**, or check snapshots before building them.
- **Save prices ahead, or save past nights**, which reverses parts of 0038
  and 0084.

Not settled; the calendar loads the model on every request that prices a
night for now.

## Testing

### What should the testing setup measure?

There's no testing setup the team trusts yet. The served model trains on every
row and stores no accuracy (decision 0085), so everything about how good a
version is comes from here. What's known it should cover:

- **Accuracy against sales**, on nights the model hasn't seen: `just backtest`
  does this today, with baselines (same weekday last year, last 4 weeks).
- **The tune-up**: whether it beats the base, and after how many days of
  manager rates. The old tuning backtest was removed for a redesign; it
  assumed the manager saw the base and booked one day ahead.
- **Closeness to the manager**, week by week: the gap between each manager rate
  and the recommendation they saw (manager minus model, and its size). A
  shrinking gap means retrains and tune-ups are working. This was the alignment
  report, removed from the API by decision 0087.
- **Open settings to test**: the manager weight (`MANAGER_SHARE`, 25%), whether
  the correction sees `month` (decision 0075), and the backtest's options
  (`--event-days`, `--start`), which may not all survive the rework.

## Process

### Should the PR template ask about migrations?

The PR template in #159 (What, Why, How to check, Notes) drops the old
checklist, including "includes an Alembic migration" and "migration applies
and rolls back". `AGENTS.md` still requires both for any model change, but
once #159 merges nothing in a PR reminds the author or the reviewer.

Options:

- **Add one line under "How to check"**: "Migrations: none, or applies and
  rolls back".
- **Rely on `AGENTS.md` and review** (as #159 has it).
- **Check it in CI**: run `alembic upgrade head` and `downgrade -1` on every
  PR that touches `database/`.

Not settled; the new template doesn't mention migrations.
