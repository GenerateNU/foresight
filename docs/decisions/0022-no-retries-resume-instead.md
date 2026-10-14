# 0022. No automatic retries; jobs commit per chunk and record where to resume

**Status:** Accepted · **Date:** 2026-10-15

## Context
A shared retry helper hid failures, slowed runs down, and spent quota on
sources whose 429 means "come back tomorrow".

## Decision
- Adapters make each request once and raise on failure.
- Jobs commit after every chunk (a month of events, a year of weather, one
  file). Each chunk records `resume_from`: the next `start` to send, or the
  next `end` when walking backwards.
- A quota or rate limit ends the job as `stopped`. Anything else ends it as
  `failed`. Both keep their saved chunks and their `resume_from`.

## Consequences
- Resuming means starting the same job again from `resume_from`. Because
  writes are upserts, overlapping is safe.
- A brief network error fails a job that a retry would have saved.
