# 0024. Weather for future nights: forecast, then typical weather

**Status:** Accepted · **Date:** 2026-10-15

## Context
The model needs weather for every night it prices, but forecasts only reach
16 days ahead.

## Decision
- Nights up to 16 days ahead use the forecast.
- Nights further out use the typical weather for that calendar week, taken
  from recorded history.
- Training uses recorded weather. When a night has both a recorded and a
  forecast value, the recorded one wins.

## Consequences
- Recorded weather must be ingested for past years, not just for the nights
  being trained on.
- Weather has little effect on far-out nights by design.
