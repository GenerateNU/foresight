import { cx } from '../../lib/cx.js'

// A white panel with a border. Pass `className` for padding or layout changes.
export default function Card({ className, ...props }) {
  return <div className={cx('rounded-card border border-stone-100 bg-white p-6', className)} {...props} />
}
