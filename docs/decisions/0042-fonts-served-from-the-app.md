# 0042. Fonts are served from the app, not Google Fonts

**Status:** Accepted · **Date:** 2026-11-01

## Context
The frontend loaded Be Vietnam Pro from Google Fonts: a stylesheet from
`fonts.googleapis.com`, then font files from `fonts.gstatic.com`. A browser
won't draw the page until a stylesheet in `<head>` arrives, so first paint
waited on two outside servers. Measured on a production build, that cost
0.1–0.3 s on a warm cache and 3.5 s on a cold one; Lighthouse, which simulates
a slow mobile connection, makes it worse. Google Fonts also sends every
visitor's IP address to Google, which European hotels have to account for.

## Decision
- Fonts ship with the app through `@fontsource` packages, imported in
  `src/main.jsx`, and Vite bundles the files.
- Only the Latin subset, and only the weights the design uses (400, 500,
  600). Each file is about 21 kB.
- Fonts use `font-display: swap`: text shows at once in the fallback font and
  switches when the font arrives, instead of staying invisible.
- No stylesheet, script or font from another origin in `index.html`.

## Consequences
- First paint depends only on our own server.
- Using a new weight means adding its import; an unlisted weight falls back
  to a synthesised one.
- Characters outside Latin (e.g. arrows) render in the fallback font.
- The brand display font (Qurova) isn't on npm. Once it's licensed, its
  files go in `src/assets/fonts/` with an `@font-face` in `index.css`.
