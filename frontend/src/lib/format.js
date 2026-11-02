/** Whole euros for display: `formatEuro(279.4)` is "€279". */
export function formatEuro(amount) {
  return `€${Math.round(amount).toLocaleString('en-IE')}`
}

/** "↑ €20" or "↓ €10"; null when nothing changed. */
export function formatChange(change) {
  if (!change) return null
  return `${change > 0 ? '↑' : '↓'} ${formatEuro(Math.abs(change))}`
}

/** "+€40" or "−€15", for factor amounts. */
export function formatSignedEuro(amount) {
  const rounded = Math.round(amount)
  if (rounded === 0) return '€0'
  return `${rounded > 0 ? '+' : '−'}€${Math.abs(rounded).toLocaleString('en-IE')}`
}
