import { NavLink } from 'react-router-dom'
import { getHotel } from '../../api/hotels.js'
import { HOTEL_ID } from '../../lib/config.js'
import { cx } from '../../lib/cx.js'
import { useAsync } from '../../hooks/useAsync.js'

const VIEWS = [
  { to: '/today', label: 'Today' },
  { to: '/calendar', label: 'Calendar' },
]

export default function TopBar() {
  const { data: hotel } = useAsync(`hotel:${HOTEL_ID}`, () => getHotel(HOTEL_ID))

  return (
    <header className="flex h-16 items-center justify-between border-b border-stone-100 px-8">
      <div className="flex items-baseline gap-3">
        <span className="text-base font-medium">{hotel?.name ?? 'Foresight'}</span>
        {hotel && (
          <span className="text-xs text-stone-500">
            {hotel.city.name}, {hotel.total_rooms} rooms
          </span>
        )}
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
