# 0066. Popups are placed by Floating UI

**Status:** Accepted · **Date:** 2026-11-19

## Context
The calendar's hover card was always in the DOM, shown by CSS on hover, and
chose its side from the night's row and column in the grid. That fit one
screen height: on a laptop, cards for the middle rows ran off the bottom of
the window. Placing a popup by the real window size means measuring where it
is when it opens, and again on scroll and resize.

## Decision
- Popups are positioned with **`@floating-ui/react`**, not hand-written
  measuring code: `useFloating` with `offset`, `flip` and `shift` (8 px from
  the window edge) and `autoUpdate`, rendered in a `FloatingPortal`.
- The card opens on hover or keyboard focus (`useFocus`, focus-visible only,
  so a mouse click doesn't pin it open), closes on Esc (`useDismiss`), and has
  the `tooltip` role (`useRole`).
- Desktop and laptop windows of any size are covered; phones aren't a target
  yet.

## Consequences
- One more dependency (about 50 kB minified in the build) in exchange for
  flipping, shifting and repositioning we don't maintain.
- The card is only in the DOM while it's open, so the cell holds a little
  state (`open`) instead of relying on CSS `:hover`.
- Other popups (menus, tooltips) should use the same library.
- The `react-hooks/refs` lint rule flags `refs.setReference` read off the
  `refs` object in JSX, so `DayCell` takes the two setters out of `refs`
  first; they are callback refs and safe to pass to `ref`.
