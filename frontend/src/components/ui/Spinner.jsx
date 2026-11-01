import { cx } from '../../lib/cx.js'

// A spinning ring. Decorative: pair it with visible text, as LoadingState does.
export default function Spinner({ className }) {
  return (
    <span
      aria-hidden="true"
      className={cx('inline-block size-5 animate-spin rounded-full border-2 border-stone-200 border-t-pine-600', className)}
    />
  )
}
