import { useMemo, useState } from 'react'
import { getRecommendations } from '../../api/recommendations.js'
import PageHeader from '../../components/layout/PageHeader.jsx'
import EmptyState from '../../components/ui/EmptyState.jsx'
import ErrorState from '../../components/ui/ErrorState.jsx'
import LoadingState from '../../components/ui/LoadingState.jsx'
import { useAsync } from '../../hooks/useAsync.js'
import { formatRoomType } from '../../lib/format.js'
import { useAuth } from '../auth/useAuth.js'
import ColorByChips from './ColorByChips.jsx'
import WeekGrid from './WeekGrid.jsx'
import { buildWeeks, rangeLabel, ratesByNight, toISODate } from './calendarUtils.js'

/** How many nights ahead the calendar prices, from tonight. The API allows up to 90. */
const NIGHTS = 30

/**
 * The Calendar screen: five weeks from Monday of this week, priced for the next NIGHTS
 * nights in one call. Nights outside that window show grey. It owns "color by" and
 * passes everything down; the pieces below it only draw what they are given.
 */
export default function CalendarPage() {
  const today = new Date()
  const [mode, setMode] = useState('price-level')
  const { hotel } = useAuth()

  const start = toISODate(today)
  const weeks = buildWeeks(today)
  const gridStart = weeks[0][0].date
  const gridEnd = weeks.at(-1).at(-1).date
  // On a Sunday the grid ends before the 30th night, so stop the window there.
  const windowEnd = toISODate(new Date(today.getFullYear(), today.getMonth(), today.getDate() + NIGHTS - 1))
  const end = windowEnd < gridEnd ? windowEnd : gridEnd

  const { data, error, loading, reload } = useAsync(`${hotel.id}:${start}:${end}`, () =>
    getRecommendations(hotel.id, { start, end }),
  )
  const byDate = useMemo(() => ratesByNight(data ?? []), [data])
  const first = data?.[0]

  return (
    <div className="flex h-full flex-col gap-4 px-8 py-6">
      <PageHeader
        eyebrow={first ? `Next ${NIGHTS} nights · ${formatRoomType(first.roomType)} room · rates before VAT` : `Next ${NIGHTS} nights`}
        title={rangeLabel(gridStart, gridEnd)}
        actions={<ColorByChips value={mode} onChange={setMode} />}
      />

      {error ? (
        <ErrorState title="Couldn't load prices" error={error} onRetry={reload} />
      ) : loading ? (
        <LoadingState label="Loading prices…" />
      ) : byDate.size === 0 ? (
        <EmptyState title={`No rates for the next ${NIGHTS} nights`} message="Rates appear once the model has priced these nights." />
      ) : (
        <WeekGrid weeks={weeks} byDate={byDate} mode={mode} />
      )}
    </div>
  )
}
