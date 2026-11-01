import { cx } from '../../lib/cx.js'

// A pill-shaped toggle, e.g. a filter. `selected` fills it in.
export default function Chip({ selected = false, className, ...props }) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      className={cx(
        'rounded-chip border px-3 py-1 text-sm transition-colors',
        'disabled:cursor-not-allowed disabled:opacity-40',
        selected
          ? 'border-stone-200 bg-stone-50 text-stone-900'
          : 'border-stone-100 text-stone-600 hover:bg-stone-25',
        className,
      )}
      {...props}
    />
  )
}
