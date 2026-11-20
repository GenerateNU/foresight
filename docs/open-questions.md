# Open questions

Questions the team hasn't settled yet. Once one is decided, record it in
[`decisions/`](decisions/README.md) and remove it from this list.

## Model

### Should training use nights that haven't happened yet?

Training reads every booked night up to the last one booked, which can be
months ahead. Those nights are only partly sold, and some have a manager rate.
Because they are the newest rows, they also land in the newest 15% of rows that
set the stored scores and the interval width. The backtest, by contrast, stops
at yesterday.

The case for keeping them: there's no ground truth to check against. The model
is trying to get as close to the manager as it can, so more data, including
future bookings and future manager rates, should help.

The case against: the stored scores then partly measure the model on
half-sold nights, and a future night's early bookings may not reflect its
final price.

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
