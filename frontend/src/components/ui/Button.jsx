import { cx } from '../../lib/cx.js'

// The one button. Pick a `variant` for its weight and a `size`; `size="icon"` is a square
// for a single glyph and needs an `aria-label`. Any other prop goes to the <button>.
const VARIANTS = {
  primary: 'bg-pine-600 text-white hover:bg-pine-700',
  secondary: 'bg-stone-50 text-stone-900 hover:bg-stone-100',
  ghost: 'text-stone-600 hover:bg-stone-25',
  danger: 'bg-error-500 text-white hover:bg-error-600',
}

const SIZES = {
  sm: 'h-8 px-3 text-sm',
  md: 'h-10 px-4 text-sm',
  icon: 'size-9',
}

export default function Button({
  variant = 'secondary',
  size = 'md',
  type = 'button',
  className,
  ...props
}) {
  return (
    <button
      type={type}
      className={cx(
        'inline-flex items-center justify-center gap-2 rounded-control font-medium transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400',
        'disabled:cursor-not-allowed disabled:opacity-40',
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...props}
    />
  )
}
