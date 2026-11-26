/**
 * A money amount from the API as a number. The API sends Decimals as strings ("279.00") so
 * no cents are lost; this is the one place they become numbers. null stays null.
 */
export function parseAmount(value) {
  return value == null ? null : Number(value)
}

/** A room type as the API names it, for display: "DOUBLE" becomes "Double". */
export function formatRoomType(name) {
  return name.charAt(0).toUpperCase() + name.slice(1).toLowerCase()
}

/** Whole euros for display: `formatEuro(279.4)` is "€279". */
export function formatEuro(amount) {
  return `€${Math.round(amount).toLocaleString('en-IE')}`
}

/** "↑ €20" or "↓ €10"; null when nothing changed. */
export function formatChange(change) {
  if (!change) return null
  return `${change > 0 ? '↑' : '↓'} ${formatEuro(Math.abs(change))}`
}

/**
 * "+€40" or "−€15", for factor amounts. Under €1 it's "+<€1" or "−<€1"; `sign` (+1 or -1)
 * says which, for amounts already rounded to 0.
 */
export function formatSignedEuro(amount, sign = Math.sign(amount) || 1) {
  const rounded = Math.round(amount)
  const symbol = (rounded || sign) > 0 ? '+' : '−'
  if (rounded === 0) return `${symbol}<€1`
  return `${symbol}€${Math.abs(rounded).toLocaleString('en-IE')}`
}
