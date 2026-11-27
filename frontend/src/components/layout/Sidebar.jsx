import { NavLink, useLocation } from 'react-router-dom'
import SignOutButton from '../../features/auth/SignOutButton.jsx'
import { cx } from '../../lib/cx.js'

// Only built screens. The rest (Today, Inbox, Signals, Reports, Upload data, Pricing rules,
// Settings) keep their placeholder routes in App.jsx and come back here as they're built.
// `also` lists other paths that belong to the item, like a night's page under Calendar.
const NAV = [{ to: '/calendar', label: 'Calendar', also: ['/nights/'] }]

/** The main navigation down the left of every signed-in page, with sign out at the bottom. Hidden on small screens. */
export default function Sidebar() {
  const { pathname } = useLocation()

  return (
    <aside className="sticky top-0 hidden h-screen w-58 shrink-0 flex-col border-r border-stone-100 bg-white p-4 md:flex">
      {/* Text wordmark until the real logo SVG is exported from Figma. */}
      <div className="mb-6 flex items-center gap-2 px-2 font-display text-2xl font-medium tracking-tight">
        <span className="size-3 rounded-full bg-dark" />
        foresight
      </div>
      <nav className="flex flex-col gap-1">
        {NAV.map(({ to, label, also = [] }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cx(
                'rounded-control px-3 py-2 text-sm',
                isActive || also.some((path) => pathname.startsWith(path)) ? 'bg-stone-50 font-medium text-stone-900' : 'text-stone-600 hover:bg-stone-25',
              )
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>
      <SignOutButton variant="ghost" className="mt-auto justify-start" />
    </aside>
  )
}
