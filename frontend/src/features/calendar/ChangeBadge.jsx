import { formatChange } from '../../lib/format.js'

/** The small "↑ €20" next to a rate. Green for up, red for down, nothing for no change. */
export default function ChangeBadge({ change }) {
  const label = formatChange(change)
  if (!label) return null
  return (
    <span className={`text-xs ${change > 0 ? 'text-price-up' : 'text-price-down'}`}>{label}</span>
  )
}
