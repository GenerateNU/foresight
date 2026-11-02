import { useId } from 'react'
import { cx } from '../../lib/cx.js'

/**
 * A labelled text field. `hint` shows under it; `error` replaces the hint and turns it red.
 * Any other prop goes to the <input>.
 */
export default function Input({ label, hint, error, className, ...props }) {
  const id = useId()
  const note = error ?? hint

  return (
    <div className={cx('flex flex-col gap-1.5', className)}>
      {label && (
        <label htmlFor={id} className="text-sm font-medium text-stone-700">
          {label}
        </label>
      )}
      <input
        id={id}
        aria-invalid={Boolean(error)}
        aria-describedby={note ? `${id}-note` : undefined}
        className={cx(
          'h-10 rounded-control border bg-white px-3 text-sm placeholder:text-stone-400',
          'focus:outline-none focus:ring-2 focus:ring-sky-400',
          error ? 'border-error-400' : 'border-stone-200',
        )}
        {...props}
      />
      {note && (
        <p id={`${id}-note`} className={cx('text-xs', error ? 'text-error-600' : 'text-stone-500')}>
          {note}
        </p>
      )}
    </div>
  )
}
