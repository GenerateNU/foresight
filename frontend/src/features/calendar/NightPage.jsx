import { Link, useParams } from 'react-router-dom'
import { saveManagerRate } from '../../api/feedback.js'
import { getRecommendations } from '../../api/recommendations.js'
import caretLeft from '../../assets/night/caret-left.svg'
import caretRight from '../../assets/night/caret-right.svg'
import Card from '../../components/ui/Card.jsx'
import EmptyState from '../../components/ui/EmptyState.jsx'
import ErrorState from '../../components/ui/ErrorState.jsx'
import LoadingState from '../../components/ui/LoadingState.jsx'
import { useAsync } from '../../hooks/useAsync.js'
import { formatEuro, formatRoomType } from '../../lib/format.js'
import { useAuth } from '../auth/useAuth.js'
import NightEvents from './NightEvents.jsx'
import WhyThisPrice from './WhyThisPrice.jsx'
import YourRate from './YourRate.jsx'
import { addDays, daysOut, longDate, monthLabel, shortDay } from './calendarUtils.js'

/**
 * One night's page, at /nights/:date: our rate, the manager's, every factor behind the
 * rate, the events, and a field to set the manager's own rate. One recommendations call
 * for that night; saving a rate fetches it again so the manager's rate shows.
 */
export default function NightPage() {
  const { date } = useParams()
  const { hotel } = useAuth()
  const { data, error, loading, reload } = useAsync(`${hotel.id}:${date}`, () =>
    getRecommendations(hotel.id, { start: date, end: date }),
  )
  const rec = data?.[0]

  // Feedback on the rate the manager saw; fetching again shows it as the manager's rate.
  async function saveRate(rate) {
    await saveManagerRate(hotel.id, { date, rate, snapshotId: rec.snapshotId })
    reload()
  }
  const out = daysOut(date)

  return (
    <div className="flex flex-col gap-6 px-8 py-6">
      <p className="text-sm text-sky-600">
        <Link to="/calendar" className="hover:underline">
          {monthLabel(date)}
        </Link>
        <span className="px-2 text-stone-400">/</span>
        {/* "Saturday 5": the month is already in the link. */}
        {longDate(date).split(' ').slice(0, 2).join(' ')}
      </p>

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-medium tracking-tight">{longDate(date)}</h1>
          <p className="mt-1 text-sm text-stone-600">
            {out > 0 ? `${out} ${out === 1 ? 'day' : 'days'} out` : out === 0 ? 'Tonight' : 'In the past'}
          </p>
        </div>
        <nav aria-label="Other nights" className="flex gap-2">
          <NightLink date={addDays(date, -1)} icon={caretLeft} before />
          <NightLink date={addDays(date, 1)} icon={caretRight} />
        </nav>
      </div>

      {error ? (
        <ErrorState title="Couldn't load this night" error={error} onRetry={reload} />
      ) : loading ? (
        <LoadingState label="Loading the night…" />
      ) : !rec ? (
        <EmptyState title="No rate for this night" message="Rates appear once the model has priced the night." />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <RateCard label={`${formatRoomType(rec.roomType)}, before VAT`} amount={rec.rate} />
            {rec.managerRate != null && <RateCard label="Manager's rate" amount={rec.managerRate} />}
          </div>

          <div className="grid items-start gap-6 lg:grid-cols-2">
            <WhyThisPrice rec={rec} />
            <div className="flex flex-col gap-6">
              <YourRate rec={rec} onSave={saveRate} />
              <NightEvents rec={rec} />
            </div>
          </div>
        </>
      )}
    </div>
  )
}

/** A headline amount, like the design's KPI card. */
function RateCard({ label, amount }) {
  return (
    <Card className="flex flex-col gap-1.5 px-5 py-4">
      <p className="text-sm text-stone-600">{label}</p>
      <p className="text-3xl font-medium tracking-tight">{formatEuro(amount)}</p>
    </Card>
  )
}

/** "‹ Fri 4" or "Sun 6 ›": a link to the night before or after, styled like a small button. */
function NightLink({ date, icon, before = false }) {
  return (
    <Link
      to={`/nights/${date}`}
      className="inline-flex h-8 items-center gap-2 rounded-control bg-stone-50 px-3 text-sm text-stone-900 hover:bg-stone-100"
    >
      {before && <img src={icon} alt="" width="16" height="16" />}
      {shortDay(date)}
      {!before && <img src={icon} alt="" width="16" height="16" />}
    </Link>
  )
}
