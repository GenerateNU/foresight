# Frontend AGENTS.md

Rules for AI coding agents working in `frontend/`, especially when turning a
Figma design into code. Read the root [`AGENTS.md`](../AGENTS.md) first, and
[`README.md`](README.md) for how to run the app and how the code is organised.

Figma file: `wCCyhvY8ggGDLx5sGcB6pN`. The design is wider than the backend:
build only what the API supports and say in the PR what you left out.

## Stack

- React 19, plain JavaScript (`.jsx`/`.js`), no TypeScript. React Router 7;
  the route table is `src/App.jsx`.
- Tailwind CSS v4 through `@tailwindcss/vite`. No CSS Modules or CSS-in-JS.
- Vite 8. ESLint 10 with `react-hooks` (including the React Compiler `refs`
  rule) and `react-refresh`.
- Popups are placed by `@floating-ui/react` ([0066](../docs/decisions/0066-popups-placed-by-floating-ui.md)).
- Fonts ship with the app through `@fontsource` ([0064](../docs/decisions/0064-fonts-served-from-the-app.md)).
- **npm 10 only.** `engine-strict` in `.npmrc` refuses npm 11, which writes a
  lockfile CI rejects. Add packages with `npx -y npm@10 install <pkg>`.
- Before every commit: `just lint` and `npm run build` (from `frontend/`).

## Tokens

Every token lives in `src/index.css`, in Tailwind v4's `@theme` block. There is
no token build step. Tailwind turns each variable into utilities:
`--color-pine-600` becomes `bg-pine-600`, `text-pine-600`, `border-pine-600`.

```css
@theme {
  --font-display: 'Qurova DEMO', 'Be Vietnam Pro', ui-sans-serif, sans-serif; /* Qurova not installed yet */
  --radius-control: 12px;   /* rounded-control: buttons, inputs */
  --radius-card: 16px;      /* rounded-card */
  --color-pine-600: #455953;
  --color-price-up: var(--color-success-500);  /* semantic: what a colour means */
}
```

- Scales (50–900): `stone` (neutral), `pine` (primary), `sky` (secondary, focus
  rings), `sand` (events), `error`, `warning`, `success`, `ember`. Plus `white`,
  `dark`, semantic `price-up`/`price-down`, and feature tokens (`demand-*`,
  `brand-panel-*`).
- **Never write a hex, `rgb()` or `rgba()` in a component.** Use the matching
  scale value. A Figma colour that isn't on a scale becomes a named token in
  `index.css` with a comment saying where in Figma it comes from.
- Prefer a semantic token when a colour carries meaning (`text-price-up`).
- Spacing and sizes use Tailwind's numeric scale (1 = 4px); any number works
  in v4 (`w-58`, `md:w-140`). Don't add spacing tokens.

### Figma variables to code

Figma's variables don't exist in code. Translate them:

| Figma | Value | Code |
|---|---|---|
| `color-text-primary` | #1f2221 | `text-stone-900` |
| `color-text-secondary` | #525b56 | `text-stone-600` |
| `color-text-inverse`, `color-text-on-brand` | white | `text-white` |
| `color-bg-canvas`, `color-surface-default` | white | `bg-white` |
| `color-surface-selected` | #f4f6f5 | `bg-stone-50` |
| `color-border-default` | #d5dbd8 | `border-stone-200` |
| `color-border-strong` | #b7c0bc | `border-stone-300` |
| `color-border-selected`, `color-brand-primary` | #1f2221 | `stone-900` (see below) |
| `color-brand-accent` | #2f6f85 | `sky-600` |
| `radius-control` / `radius-sm` | 12px / 4px | `rounded-control` / `rounded-sm` |
| `space-N` | N ÷ 25 px | Tailwind N ÷ 100: `space-200` → `2`, `space-400` → `4`, `space-2000` → `20` |
| `font-size-100/200/300/400/500/800/900/1100` | 12/13/14/16/18/30/36/60 px | `text-xs` / `text-[13px]` / `text-sm` / `text-base` / `text-lg` / `text-3xl` / `text-4xl` / `text-6xl` |
| `font-family-body` | Be Vietnam Pro | default (`font-sans`) |
| "Qurova DEMO" (display styles) | | `font-display` |

**Open question:** Figma's `color-brand-primary` is near-black, but
`Button variant="primary"` is `bg-pine-600`. Keep the Button as it is until
the team decides; don't restyle it for one screen.

## Components

- `src/components/ui/`: shared building blocks. `src/components/layout/`: the
  app frame. `src/features/<name>/`: everything for one screen. A piece moves
  to `components/ui/` once a second screen needs it.
- **Reuse before you build.** Don't add a component unless a screen needs one.
  A design that needs a variant gets it added to the component, not styled in
  the screen.
- Pattern: a function component per file, default export, a `/** */` comment
  above it. Variants are maps from a name to classes, joined with `cx()`
  (`src/lib/cx.js`), `className` last, other props passed through.

```jsx
const VARIANTS = { primary: 'bg-pine-600 text-white hover:bg-pine-700', secondary: 'bg-stone-50 …' }
export default function Button({ variant = 'secondary', size = 'md', href, className, ...props }) {
  const Element = href ? 'a' : 'button'
  return <Element className={cx('inline-flex … rounded-control', VARIANTS[variant], SIZES[size], className)} {...props} />
}
```

| Component | Props | Figma |
|---|---|---|
| `Button` | `variant` primary/secondary/ghost/danger, `size` sm/md/icon, `href` | Button |
| `Input` | `label`, `hint`, `error` | Input (no icon or suffix yet) |
| `Card` | `className` | panels |
| `Badge` | `tone` neutral/info/success/warning/error | status labels |
| `Chip` | `selected`, `disabled`, `title` | filter pills |
| `Spinner` | `className` | |
| `LoadingState` / `EmptyState` / `ErrorState` | `label` / `title`, `message`, `action` / `title`, `error`, `onRetry` | none yet |
| `PageHeader` | `eyebrow`, `title`, `actions` | page title block |

There's no Storybook. The dev-only gallery at `/components`
(`src/pages/ComponentsPage.jsx`) shows every shared component; add new ones
there.

## Styling

- Utility classes only. Global CSS is `@theme` plus one `body` rule in
  `@layer base`.
- Write every class name out in full; Tailwind finds classes by scanning the
  source. Never build one from pieces (`bg-demand-${n}`): use a lookup array,
  as `features/calendar/colorModes.js` does.
- Arbitrary values only for Figma geometry the scale lacks (`tracking-[-1.2px]`,
  `leading-[1.1]`), never for colours. Inline `style` only for what utilities
  can't express (a multi-stop gradient), built from token variables.
- Mobile-first with `md:`. Desktop and laptop are the target; hide secondary
  panels below `md` (`hidden … md:flex`).
- Focus: `focus-visible:ring-2 focus-visible:ring-sky-400`. Disabled:
  `disabled:cursor-not-allowed disabled:opacity-40`.
- Popups use Floating UI (`useFloating` with `offset`, `flip`, `shift`,
  `autoUpdate`, in a `FloatingPortal`), as `features/calendar/DayCell.jsx` does.

## Assets and icons

- Images and SVGs go in `src/assets/<feature>/` with kebab-case names for what
  they show, imported as modules so Vite fingerprints them. `public/` is only
  for files referenced by absolute URL (`/favicon.svg`). There's no CDN.
- Download every asset `get_design_context` returns with `curl -L`. Never leave
  a `figma.com/api/mcp/asset` URL in code; they expire after 7 days.
- Use them as `<img>` with the SVG's own `width` and `height`, and `alt=""`
  when decorative:

```jsx
import googleIcon from '../../assets/sign-in/google.svg'
<img src={googleIcon} alt="" width="18" height="18" />
```

- No icon library yet. Figma uses Phosphor icons; download the SVG per use and
  ask before adding an icon package.
- The logo mark is `src/assets/sign-in/logo-mark.svg`; the Sidebar still uses a
  text wordmark, and Figma marks its Logo component as a placeholder.

## Screens

1. Pages fetch, components draw: a page calls `src/api/` through `useAsync` and
   passes plain data down.
2. Every load renders `LoadingState`, `ErrorState` (with `onRetry`) and
   `EmptyState` before the real content.
3. Hotel-scoped data takes `hotel.id` from `useAuth()`
   (`features/auth/useAuth.js`), never from config.
4. Pure logic goes in plain `.js` files in the feature.
5. When an endpoint's response changes, change its mock in `src/api/mocks/` in
   the same PR.
6. Record a design choice worth keeping in `docs/decisions/`; check open PRs
   for numbers already taken first.
