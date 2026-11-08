# 0050. The manager sends the rate they chose; the verdict is worked out from it

**Status:** Accepted · **Date:** 2026-11-07

## Context
[0043](0043-manager-feedback-is-versioned.md) asks the manager for a verdict
(too high, too low or about right) and, optionally, the rate they'd charge.
The hotel's PMS can't export the rates set for future nights, so the app is
where the manager records the rate they actually choose. Once they enter it,
the verdict adds nothing: it can be worked out by comparing their rate with
ours, and asking for both lets the two contradict each other (a "too low"
sent with a lower rate).

## Decision
- `POST /hotels/{id}/feedback` takes `rate` (required): the rate the manager
  chose. It no longer takes `verdict`; sending one is a 422.
- `snapshot_id` is required: the recommendation the manager saw. Its rate is
  what the manager's rate is compared with.
- The server sets `verdict` from the two (`domain/feedback.verdict_for`):
  - the manager's rate is higher: ours was `TOO_LOW`;
  - lower: `TOO_HIGH`;
  - the same to the cent: `ABOUT_RIGHT`.
- The manager sends feedback only when they change our rate. A night with no
  feedback keeps the recommendation: it counts as accepted, and the manager
  can change it later (a new version, as in 0043).
- A new reason tag, `ONE_OFF`, for something that won't happen again (a
  buyout, a private event). It is stored like the others; nothing uses it yet.
- Tags and free text stay optional, as in 0043.
- No schema change. `verdict` stays a required column, now always set by the
  server. `rate` and `snapshot_id` stay nullable in the database: rows saved
  before this decision may have no rate, and deleting a snapshot still clears
  the link.

## Consequences
- Feedback can't be given on a night that never had a recommendation, since
  there's nothing to compare with. Past nights keep the snapshots made for
  them while they were ahead, so a night that was ever recommended can still
  get feedback after it.
- `verdict` now means "how the manager's rate compares with ours", not the
  manager's opinion. Old rows keep the verdict the manager chose.
- **Training is unchanged, and the two don't fit together yet.**
  [0044](0044-train-on-feedback-given-after-the-night.md) compares the
  manager's rate with the night's *recorded* rate, and only uses feedback
  given after the night. If the manager charged the rate they entered, the
  recorded rate equals it, so after-night feedback with a verdict of too high
  or too low counts as "a rate that contradicts the verdict" and halves the
  night's weight instead of helping. Feedback given before the night, now the
  usual case, isn't used at all. How training should use the manager's rate
  (a daily top-up of the model is planned) needs its own decision.
