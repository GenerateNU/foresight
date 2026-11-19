import {
  FloatingPortal,
  autoUpdate,
  flip,
  offset,
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
 * One night in the grid. `rec` is undefined for days outside the month or with no price.
 * Hovering, or focusing it with the keyboard, opens the night's card wherever it fits
 * on screen (docs/decisions/0058).
 */
export default function DayCell({ day, rec, mode, context }) {
  const [open, setOpen] = useState(false)
  const { refs, floatingStyles, context: floatingContext } = useFloating({
    open,
    onOpenChange: setOpen,
    placement: 'bottom',
    middleware: [offset(8), flip({ padding: 8 }), shift({ padding: 8 })],
    whileElementsMounted: autoUpdate,
  })
  const { setReference, setFloating } = refs
  // useFocus only opens on keyboard focus: a mouse click also focuses the night, and
  // would otherwise keep its card open while hovering others.
  const { getReferenceProps, getFloatingProps } = useInteractions([
    useHover(floatingContext),
    useFocus(floatingContext),
    useDismiss(floatingContext),
    useRole(floatingContext, { role: 'tooltip' }),
  ])

  if (!day.inMonth || !rec) {
    return (
      <div className="min-h-28 rounded-card border border-stone-100 bg-stone-25 p-3 text-stone-300">
        {day.day}
      </div>
    )
  }

  const { bg, dot } = nightStyle(mode, rec, context)

  return (
    <div
      ref={setReference}
      tabIndex={0}
      className={`min-h-28 rounded-card border border-stone-100 p-3 outline-none focus-visible:ring-2 focus-visible:ring-sky-400 ${bg}`}
      {...getReferenceProps()}
    >
      <div className="flex items-center justify-between text-sm">
        <span className="flex items-center gap-1.5">
          {day.day}
          <span className={`size-1.5 rounded-full ${dot}`} />
        </span>
        <ChangeBadge change={rec.change} />
      </div>
      <p className="mt-1 text-xl font-medium">{formatEuro(rec.rate)}</p>
      {rec.events[0] && (
        <p className="mt-2 truncate rounded-sm bg-white px-2 py-0.5 text-xs text-stone-700">
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
