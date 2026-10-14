# 0023. A stay night is a local date in the city's timezone

**Status:** Accepted · **Date:** 2026-10-15

## Context
Sources report times in UTC, in the venue's zone, or as plain dates. A
21:00 concert must count toward that night, not the next UTC day.

## Decision
- Every per-night value is stored as a `Date` local to the city: stay
  nights, weather days, event start and end dates, flight arrival days.
- "Today" is today in the city's timezone.
- Instants (when something was fetched or happened) are stored as
  timezone-aware timestamps.

## Consequences
- Signals join to stay nights by date, with no conversion when read.
- Every city must have a valid IANA timezone.
