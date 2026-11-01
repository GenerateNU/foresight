import Spinner from './Spinner.jsx'

// What a page or panel shows while its data loads.
export default function LoadingState({ label = 'Loading…' }) {
  return (
    <div role="status" className="flex items-center justify-center gap-3 py-16 text-sm text-stone-500">
      <Spinner />
      {label}
    </div>
  )
}
