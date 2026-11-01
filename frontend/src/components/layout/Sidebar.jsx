import { NavLink } from 'react-router-dom'
import { cx } from '../../lib/cx.js'

const NAV = [
  { to: '/today', label: 'Today' },
  { to: '/calendar', label: 'Calendar' },
  { to: '/inbox', label: 'Inbox' },
  { to: '/signals', label: 'Signals' },
  { to: '/reports', label: 'Reports' },
  { to: '/upload', label: 'Upload data' },
  { to: '/pricing-rules', label: 'Pricing rules' },
  { to: '/settings', label: 'Settings' },
]

export default function Sidebar() {
  return (
    <aside className="hidden w-58 shrink-0 flex-col border-r border-stone-100 bg-white p-4 md:flex">
      {/* Text wordmark until the real logo SVG is exported from Figma. */}
      <div className="mb-6 flex items-center gap-2 px-2 font-display text-2xl font-medium tracking-tight">
        <span className="size-3 rounded-full bg-dark" />
        foresight
      </div>
      <nav className="flex flex-col gap-1">
        {NAV.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cx(
                'rounded-control px-3 py-2 text-sm',
                isActive ? 'bg-stone-50 font-medium text-stone-900' : 'text-stone-600 hover:bg-stone-25',
              )
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
