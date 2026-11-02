# 0041. Waiting is fine; leaving the manager guessing isn't

**Status:** Accepted · **Date:** 2026-11-01

## Context
Most screens wait on the API, and some on slow work: pricing a month of
nights, an upload, a training run ([0020](0020-jobs-in-the-api-process.md)).
We can't make all of it instant, and a manager can live with a wait. What
costs their trust is not knowing what's happening: a blank page, a spinner
with no end, content that jumps around, or a failure that says nothing.

## Decision
The frontend accepts waiting and always shows what's going on:

1. **The frame never waits.** Navigation, the page header and controls show
   at once. Only the area that needs data waits.
2. **Placeholders look like what's coming.** When the shape is known, use
   `Skeleton` blocks in that shape (the calendar shows an empty grid). Use
   `LoadingState` only when the shape isn't known.
3. **No flashes.** Placeholders fade in after 150 ms (`animate-appear`), so a
   fast answer goes straight to the content.
4. **Keep what's on screen while refreshing it.** After a save or a retry,
   the current content stays, with a small "Updating…" note (`useAsync`'s
   `refreshing`). Swap to placeholders only when what's shown would be wrong,
   such as another month.
5. **Long work says what it's doing.** Anything that takes more than a few
   seconds (uploads, jobs) shows its progress from `GET /jobs/{id}`,
   lets the manager leave the page, and says when it's done.
6. **Say how fresh the data is.** Where numbers depend on refreshed data,
   show when it last refreshed, from the freshness endpoint
   ([0039](0039-freshness-reports-dates-only.md)).
7. **Failures say what failed and offer a way out.** `ErrorState` with a
   retry. A failed save keeps what the manager typed.
8. **Empty isn't an error.** `EmptyState` says why it's empty and what to do
   next.
9. **Speed is judged on a production build** (`npm run build && npm run
   preview`), never the dev server, and nothing from another origin blocks
   the first paint ([0042](0042-fonts-served-from-the-app.md)).

## Consequences
- A screen isn't done until its loading, refreshing, empty and error states
  are; reviews check them, and `/components` shows the building blocks.
- Skeletons have to follow the layout they stand in for when it changes.
- No optimistic updates by default: rates come from the model, so the UI
  waits for the API's answer instead of guessing it.
- Screens that start long work poll `GET /jobs/{id}`, which already reports
  status and progress counts, rather than guessing how far along it is.
