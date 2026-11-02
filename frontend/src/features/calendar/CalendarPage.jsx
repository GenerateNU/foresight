import { useMemo, useState } from 'react'
import { getRecommendations } from '../../api/recommendations.js'
import PageHeader from '../../components/layout/PageHeader.jsx'
import Button from '../../components/ui/Button.jsx'
import EmptyState from '../../components/ui/EmptyState.jsx'
import ErrorState from '../../components/ui/ErrorState.jsx'
import LoadingState from '../../components/ui/LoadingState.jsx'
import { HOTEL_ID } from '../../lib/config.js'
import { useAsync } from '../../hooks/useAsync.js'
import ColorByChips from './ColorByChips.jsx'
import MonthGrid from './MonthGrid.jsx'
import { buildMonthGrid, lowestRatePerNight, monthLabel } from './calendarUtils.js'

/**
 * The Calendar screen: owns "which month" and "color by", fetches that month's prices,
 * and passes everything down. The pieces below it only draw what they are given.
 */
export default function CalendarPage() {
  const today = new Date()
  const [{ year, month }, setMonth] = useState({ year: today.getFullYear(), month: today.getMonth() })
  const [mode, setMode] = useState('demand')

  const weeks = useMemo(() => buildMonthGrid(year, month), [year, month])
  const start = weeks[0][0].date
  const end = weeks.at(-1).at(-1).date

  const { data, error, loading, reload } = useAsync(`${start}:${end}`, () =>
    getRecommendations(HOTEL_ID, { start, end }),
  )
  const byDate = useMemo(() => lowestRatePerNight(data ?? []), [data])

  function shiftMonth(delta) {
    const next = new Date(year, month + delta, 1)
    setMonth({ year: next.getFullYear(), month: next.getMonth() })
  }

  return (
    <div className="space-y-6 px-8 py-8">
      <PageHeader
        eyebrow="Rates shown are the lowest available"
        title={monthLabel(year, month)}
        actions={
          <>
            <Button size="icon" aria-label="Previous month" onClick={() => shiftMonth(-1)}>
              ‹
            </Button>
            <Button size="sm" onClick={() => setMonth({ year: today.getFullYear(), month: today.getMonth() })}>
              This month
            </Button>
            <Button size="icon" aria-label="Next month" onClick={() => shiftMonth(1)}>
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
        <EmptyState title="No prices for this month" message="Rates appear once the model has priced these nights." />
      ) : (
        <MonthGrid weeks={weeks} byDate={byDate} mode={mode} />
      )}
    </div>
  )
}
