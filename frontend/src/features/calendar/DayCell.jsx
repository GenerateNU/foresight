import {
  FloatingPortal,
  autoUpdate,
  flip,
  offset,
  safePolygon,
  shift,
  useDismiss,
  useFloating,
  useFocus,
  useHover,
  useInteractions,
  useRole,
} from '@floating-ui/react'
import { useState } from 'react'
import ChangeBadge from './ChangeBadge.jsx'
import { formatEuro } from '../../lib/format.js'
import DayPopover from './DayPopover.jsx'
import { nightStyle } from './colorModes.js'

/**
 * One night in the grid. `rec` is undefined for nights outside the priced window.
 * Hovering, or focusing it with the keyboard, opens the night's card wherever it fits
 * on screen (docs/decisions/0066). The pointer can move into the card to reach its link.
 */
export default function DayCell({ day, rec, mode, context }) {
  const [open, setOpen] = useState(false)
  const { refs, floatingStyles, context: floatingContext } = useFloating({
    open,
    onOpenChange: setOpen,
    // Beside the night, not below: the grid fills the screen, so above or below a row
    // rarely has room for the card, while sideways it can slide up or down to fit.
    placement: 'right',
    middleware: [
      offset(8),
      flip({ padding: 8 }),
      shift({ padding: 8 }),
    ],
    whileElementsMounted: autoUpdate,
  })
  const { setReference, setFloating } = refs
  // useFocus only opens on keyboard focus: a mouse click also focuses the night, and
  // would otherwise keep its card open while hovering others.
  const { getReferenceProps, getFloatingProps } = useInteractions([
    useHover(floatingContext, { handleClose: safePolygon() }),
    useFocus(floatingContext),
    useDismiss(floatingContext),
    useRole(floatingContext, { role: 'dialog' }),
  ])

  if (!rec) {
    return (
      <div className="min-h-0 rounded-card border border-stone-100 bg-stone-25 p-2.5 text-sm text-stone-300">
        {day.label}
      </div>
    )
  }

  const { bg, dot } = nightStyle(mode, rec, context)

  return (
    <div
      ref={setReference}
      tabIndex={0}
      className={`min-h-0 overflow-hidden rounded-card border border-stone-100 p-2.5 outline-none focus-visible:ring-2 focus-visible:ring-sky-400 ${bg}`}
      {...getReferenceProps()}
    >
      <div className="flex items-center justify-between text-sm">
        <span className="flex items-center gap-1.5">
          {day.label}
          <span className={`size-1.5 rounded-full ${dot}`} />
        </span>
        <ChangeBadge change={rec.change} />
      </div>
      <p className="mt-1 text-xl font-medium">{formatEuro(rec.rate)}</p>
      {rec.events[0] && (
        <p className="mt-1.5 truncate rounded-sm bg-white px-2 py-0.5 text-xs text-stone-700">
          {rec.events[0].title}
        </p>
      )}
      {open && (
        <FloatingPortal>
          <DayPopover
            rec={rec}
            ref={setFloating}
            style={floatingStyles}
            {...getFloatingProps()}
          />
        </FloatingPortal>
      )}
    </div>
  )
}
