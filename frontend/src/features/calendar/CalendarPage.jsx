import { useMemo, useState } from 'react'
import { getRecommendations } from '../../api/recommendations.js'
import PageHeader from '../../components/layout/PageHeader.jsx'
import Button from '../../components/ui/Button.jsx'
import EmptyState from '../../components/ui/EmptyState.jsx'
import ErrorState from '../../components/ui/ErrorState.jsx'
import LoadingState from '../../components/ui/LoadingState.jsx'
import { useAsync } from '../../hooks/useAsync.js'
import { useAuth } from '../auth/useAuth.js'
import ColorByChips from './ColorByChips.jsx'
import MonthGrid from './MonthGrid.jsx'
import { buildMonthGrid, monthLabel, ratesByNight, toISODate } from './calendarUtils.js'

/** How many nights ahead the calendar prices, from tonight. The API allows up to 90. */
const NIGHTS = 30

/**
 * The Calendar screen: fetches the next NIGHTS nights once, owns "which month" and
 * "color by", and passes everything down. The pieces below it only draw what they are
 * given. Month navigation stays within the months those nights fall in.
 */
export default function CalendarPage() {
  const today = new Date()
  const [{ year, month }, setMonth] = useState({ year: today.getFullYear(), month: today.getMonth() })
  const [mode, setMode] = useState('price-level')
  const { hotel } = useAuth()

  const weeks = useMemo(() => buildMonthGrid(year, month), [year, month])
  const start = toISODate(today)
  const last = new Date(today.getFullYear(), today.getMonth(), today.getDate() + NIGHTS - 1)
  const end = toISODate(last)
  const isFirstMonth = year === today.getFullYear() && month === today.getMonth()
  const isLastMonth = year === last.getFullYear() && month === last.getMonth()

  const { data, error, loading, reload } = useAsync(`${hotel.id}:${start}:${end}`, () =>
    getRecommendations(hotel.id, { start, end }),
  )
  const byDate = useMemo(() => ratesByNight(data ?? []), [data])
  const roomType = data?.[0]?.roomType

  function shiftMonth(delta) {
    const next = new Date(year, month + delta, 1)
    setMonth({ year: next.getFullYear(), month: next.getMonth() })
  }

  return (
    <div className="space-y-6 px-8 py-8">
      <PageHeader
        eyebrow={roomType ? `Rates for the ${roomType} room` : 'Rates'}
        title={monthLabel(year, month)}
        actions={
          <>
            <Button size="icon" aria-label="Previous month" disabled={isFirstMonth} onClick={() => shiftMonth(-1)}>
              ‹
            </Button>
            <Button size="sm" onClick={() => setMonth({ year: today.getFullYear(), month: today.getMonth() })}>
              This month
            </Button>
            <Button size="icon" aria-label="Next month" disabled={isLastMonth} onClick={() => shiftMonth(1)}>
              ›
            </Button>
          </>
        }
      />

      <ColorByChips value={mode} onChange={setMode} />

      {error ? (
        <ErrorState title="Couldn't load prices" error={error} onRetry={reload} />
      ) : loading ? (
        <LoadingState label="Loading prices…" />
      ) : byDate.size === 0 ? (
        <EmptyState title={`No rates for the next ${NIGHTS} nights`} message="Rates appear once the model has priced these nights." />
      ) : (
        <MonthGrid weeks={weeks} byDate={byDate} mode={mode} />
      )}
    </div>
  )
}
