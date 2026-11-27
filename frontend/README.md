# Foresight frontend

React + Vite + Tailwind CSS (v4) + React Router. Plain JavaScript.

## Run it

From the repo root:

```sh
just frontend-install        # npm ci, with npm 10
just frontend                # http://localhost:5173
just frontend --mocks        # same, with fake data and no backend
just lint                    # ruff + ESLint
```

**Use npm 10.** CI runs Node 22 (`.nvmrc`) and npm 10, and npm 11 writes a `package-lock.json`
CI rejects, so `engine-strict` in `.npmrc` makes `npm install` and `npm ci` refuse any other npm.
On a newer npm, add or remove packages with `npx -y npm@10 install <pkg>`, or switch to Node 22
(`nvm use`).

Or from `frontend/`: `npm run dev`, `npm run lint`, `npm run build`. To change a setting,
`cp .env.example .env.local` and edit it.

| Setting | What it does |
| --- | --- |
| `VITE_API_URL` | Where the backend lives. Default `http://localhost:8000` (`just dev` from the repo root). |
| `VITE_USE_MOCKS` | `true` serves fake responses from `src/api/mocks`, so you don't need the backend running. |

Open http://localhost:5173/components in dev to see every shared component.

## How the code is organized

```
src/
  main.jsx            starts React and the router
  App.jsx             the route table: URL -> page
  index.css           Tailwind + the design tokens from Figma (colors, fonts, radii)
  api/                the ONLY code that talks to the backend
    client.js           fetch wrapper: base URL, cookies, errors, 401 -> sign in, mocks
    auth.js             the Google sign-in link, and the page to return to after it
    recommendations.js  one function per endpoint, returns clean data
    uploads.js          the Guestline upload and its jobs
    mocks/              fake responses, same shapes as the real API
  lib/                small helpers with no React in them (config, cx)
  hooks/              reusable React logic (useAsync: load data, track loading/error, retry)
  components/
    layout/             the shell (sidebar, top bar) and PageHeader
    ui/                 shared building blocks: Button, Card, Input, Badge, Chip, states
  features/           one folder per built screen; everything for it lives together
    auth/               who's signed in (AuthProvider, useAuth, RequireAuth), sign-in and sign-out
    calendar/           the calendar: page, five-week grid, hover card, colour modes, night page
    upload/             the daily Guestline upload and each file's job status
  pages/              placeholder, not-found and the dev component gallery
```

## Rules of thumb

- **Reuse before you style.** Need a button, panel, field or status? Use `components/ui/`. If a screen needs a variant, add it to the component, not to the screen.
- **Colors come from tokens.** Use `bg-pine-600`, `text-stone-500`, `text-price-up`. Never write a hex in a component. To change a color, change it in `index.css`.
- **Every load has three states.** Show `LoadingState`, `ErrorState` (with `onRetry={reload}` from `useAsync`) or `EmptyState` before the real content.
- **Components draw, they don't fetch.** Pages fetch (via `api/` + `useAsync`) and pass plain data down.
- **A feature folder owns its screen.** A piece moves to `components/ui/` once a second screen needs it.
- **Pure logic goes in plain `.js` files** so it can be tested without React.
- **Popups are placed by Floating UI** (`@floating-ui/react`), so they flip and shift to stay on screen (docs/decisions/0066).
- **A breakdown in whole euros must add up** to the total it explains: use `roundForDisplay`, not per-line rounding (docs/decisions/0065).
- **Comments: one `/** … */` above each export.** Say what it's for and what its props or arguments mean; editors show it on hover. Inside a function, comment only a non-obvious *why*, never what a line does. A comment at the top of a file only when the whole file needs context (e.g. `index.css`, `config.js`).
- **Mocks follow the API.** When an endpoint's response changes, change its mock in the same PR.

## Adding a screen

1. Add the endpoint call in `src/api/` and its mock in `src/api/mocks/`.
2. Make `src/features/<name>/<Name>Page.jsx`: `PageHeader`, then fetch with `useAsync` and render the loading, error, empty and loaded states.
3. Swap its placeholder in `src/App.jsx` for the new page.

## Signing in

`AuthProvider` (in `main.jsx`) asks `GET /auth/me` once. Read it with `useAuth()`:
`{ user, hotels, hotel, status, retry }`, where `hotel` is the first of `hotels` (one hotel
per user for now) and `status` is `loading`, `authed`, `anon`, `no-hotel` or `error`. Anything
hotel-scoped takes `hotel.id` from there. `RequireAuth` wraps every page in the app shell and
shows a full-screen state for everything but `authed`; those states have no Figma design yet.
With `VITE_USE_MOCKS=true`, `/auth/me` returns one hotel (Beresford, Dublin).

A 401 from the API saves the current page in `sessionStorage` and sends the browser to
`/sign-in`. Its button is a plain link to the API's `/auth/google/login`, not a `fetch`. After
Google, the API always redirects to the app's root (`FRONTEND_URL`) and ignores any `next`
parameter (docs/decisions/0040), so the root route reads the saved page and goes back to it,
or to the calendar.

## Not built yet

- An error on the sign-in page when Google sign-in fails: the API's callback shows its own error and doesn't come back to the app.
- Choosing between hotels, for a user linked to more than one.
- Every screen behind a placeholder route.
- Calendar: the occupancy, comp set gap and weather colour modes (waiting on booking data and competitor rates), and the price change colour mode and up/down price badge, which work once the API returns `previous_rate` (issue #96).
