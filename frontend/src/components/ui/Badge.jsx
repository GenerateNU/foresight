import { cx } from '../../lib/cx.js'

// A small coloured label for a status. `tone` says what it means, not what colour it is.
const TONES = {
  neutral: 'bg-stone-50 text-stone-700',
  info: 'bg-sky-50 text-sky-700',
  success: 'bg-success-50 text-success-700',
  warning: 'bg-warning-50 text-warning-700',
  error: 'bg-error-50 text-error-700',
}

export default function Badge({ tone = 'neutral', className, ...props }) {
  return (
    <span
      className={cx('inline-flex items-center rounded-chip px-2.5 py-0.5 text-xs font-medium', TONES[tone], className)}
      {...props}
    />
  )
}
