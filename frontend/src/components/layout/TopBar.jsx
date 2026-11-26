import { NavLink } from 'react-router-dom'
import { useAuth } from '../../features/auth/useAuth.js'
import { cx } from '../../lib/cx.js'

const VIEWS = [
  { to: '/today', label: 'Today' },
  { to: '/calendar', label: 'Calendar' },
]

/** The bar above every signed-in page: the hotel's name and city, and the Today / Calendar switch. */
export default function TopBar() {
  const { hotel } = useAuth()

  return (
    <header className="flex h-16 items-center justify-between border-b border-stone-100 px-8">
      <div className="flex items-baseline gap-3">
        <span className="text-base font-medium">{hotel.name}</span>
        {hotel.city?.name && <span className="text-xs text-stone-500">{hotel.city.name}</span>}
      </div>

      <div className="flex rounded-control border border-stone-100 p-0.5 text-sm">
        {VIEWS.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cx('rounded-control px-4 py-1.5', isActive ? 'bg-stone-50 text-stone-900' : 'text-stone-500')
            }
          >
            {label}
          </NavLink>
        ))}
      </div>
    </header>
  )
}
