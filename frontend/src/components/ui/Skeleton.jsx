import { cx } from '../../lib/cx.js'

/**
 * A grey pulsing block standing in for content that's loading. Give it the content's size
 * and shape with `className`, e.g. `h-6 w-24`. It fades in after a moment, so a fast
 * answer never flashes it (docs/decisions/0041). Decorative: put `role="status"` and an
 * `aria-label` on the area it fills.
 */
export default function Skeleton({ className }) {
  return (
    <div aria-hidden="true" className={cx('animate-appear overflow-hidden rounded-control', className)}>
      <div className="size-full animate-pulse bg-stone-100" />
    </div>
  )
}
