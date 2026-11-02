import Spinner from './Spinner.jsx'

/**
 * What a page or panel shows while its data loads, when the content's shape isn't known.
 * When it is, use Skeleton blocks in that shape instead (docs/decisions/0041).
 */
export default function LoadingState({ label = 'Loading…' }) {
  return (
    <div role="status" className="flex animate-appear items-center justify-center gap-3 py-16 text-sm text-stone-500">
      <Spinner />
      {label}
    </div>
  )
}
