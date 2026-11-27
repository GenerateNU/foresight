import Badge from '../../components/ui/Badge.jsx'
import { dateRange } from './uploadUtils.js'

const TONES = { queued: 'neutral', running: 'info', succeeded: 'success', stopped: 'warning', failed: 'error', cancelled: 'neutral' }
const REPORT_NAMES = { reservations: 'Daily New Reservations' }

/** One uploaded file's job: which report it was read as, its status, and what happened. */
export default function JobStatus({ job }) {
  return (
    <li className="flex items-start justify-between gap-4 py-3 first:pt-0 last:pb-0">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{job.file}</p>
        <p className="text-xs text-stone-500">
          {REPORT_NAMES[job.kind] ?? job.kind} · {detail(job)}
        </p>
        {job.error && <p className="mt-1 text-xs text-error-700">{job.error}</p>}
      </div>
      <Badge tone={TONES[job.status]} className="shrink-0 capitalize">
        {job.status}
      </Badge>
    </li>
  )
}

function detail(job) {
  const n = (count) => count.toLocaleString('en-IE')
  switch (job.status) {
    case 'queued':
      return `${n(job.rows)} rows, waiting its turn`
    case 'running':
      return `Saving rows: ${n(job.rowsDone)} of ${n(job.rowsTotal)}`
    case 'succeeded': {
      const { new: added = 0, updated = 0 } = job.outcomes
      const booked = job.firstDate ? `, booked ${dateRange(job.firstDate, job.lastDate)}` : ''
      return `${n(job.rows)} rows${booked}: ${n(added)} new, ${n(updated)} updated`
    }
    case 'cancelled':
      return 'Taken out of the queue'
    default:
      return `Stopped after ${n(job.rowsDone)} of ${n(job.rowsTotal)} rows. Upload the file again to finish.`
  }
}
