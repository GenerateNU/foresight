// Full class names on purpose: Tailwind finds classes by scanning for complete strings.
const DEMAND_BG = [
  'bg-demand-1', 'bg-demand-2', 'bg-demand-3', 'bg-demand-4', 'bg-demand-5',
]
const DEMAND_DOT = [
  'bg-demand-dot-1', 'bg-demand-dot-2', 'bg-demand-dot-3', 'bg-demand-dot-4', 'bg-demand-dot-5',
]

const NEUTRAL = { bg: 'bg-stone-25', dot: 'bg-stone-300' }

/**
 * What the "Color by" chips do. Each mode's `style(rec, { demandLevel })` turns a night's
 * recommendation into `{ bg, dot }` classes. A mode with `disabled` says why it's off.
 */
export const COLOR_MODES = [
  {
    id: 'demand',
    label: 'Demand',
    style: (rec, { demandLevel }) => ({
      bg: DEMAND_BG[demandLevel - 1],
      dot: DEMAND_DOT[demandLevel - 1],
    }),
  },
  {
    id: 'price-change',
    label: 'Price change',
    style: (rec) => {
      if (!rec.change) return NEUTRAL
      return rec.change > 0
        ? { bg: 'bg-success-50', dot: 'bg-success-400' }
        : { bg: 'bg-error-50', dot: 'bg-error-400' }
    },
  },
  {
    id: 'events',
    label: 'Events',
    style: (rec) =>
      rec.events.length > 0 ? { bg: 'bg-sand-50', dot: 'bg-sand-400' } : NEUTRAL,
  },
  // Designed but waiting on data the backend doesn't have yet (see the README's "Not built yet").
  { id: 'occupancy', label: 'Occupancy', disabled: 'Needs booking data' },
  { id: 'comp-set', label: 'Comp set gap', disabled: 'Needs competitor rates' },
  { id: 'weather', label: 'Weather', disabled: 'Coming soon' },
]

/** The `{ bg, dot }` classes for one night under `modeId`; neutral for a disabled mode. */
export function nightStyle(modeId, rec, context) {
  const mode = COLOR_MODES.find((m) => m.id === modeId)
  return mode?.style ? mode.style(rec, context) : NEUTRAL
}
