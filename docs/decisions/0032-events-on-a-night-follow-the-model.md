# 0032. The events shown for a night follow the model's rule

**Status:** Accepted · **Date:** 2026-10-26

## Context
The calendar and night detail list the events affecting each night. If that
list used a different rule from the model's features, the manager could see
events that don't move the rate, or miss ones that do.

## Decision
- `event.events_by_night` decides which events affect a night: live events in
  the hotel's city, on every night from their start to their end date
  (inclusive), in a category the model counts (`ATTENDED_CATEGORIES` plus
  public and school holidays).
- Cancelled and deleted events are hidden, as in the events endpoint.
- A night's events are sorted by expected attendance, then local rank, biggest
  first. Unknown values sort last. Events with no venue or attendance still show.
- A multi-day event carries `day_number` and `day_count` ("day 2 of 3"),
  counted from its real start date even when the requested range begins later.
- ~~`night.recommendation_range` prices each night separately, so a range is
  limited to 62 nights.~~ Replaced by
  [0038](0038-recommendations-reused-while-inputs-hold.md): each recommendation
  carries its night's events, and a range is one batch of up to 90 nights.

## Consequences
- If the model's category list changes, the shown events change with it.
- Categories the model ignores (disasters, airport delays) don't appear.
