import { useState } from 'react'
import Button from '../../components/ui/Button.jsx'
import Card from '../../components/ui/Card.jsx'

/** Events shown before "Show all"; a busy night in Dublin has over 70. */
const FIRST_EVENTS = 8

/**
 * The events on the night that the model counted. When no events were loaded for the
 * night (`eventsSource` "missing") the list is unknown, not empty, so it says so. The API
 * sends the largest first, so the first FIRST_EVENTS are the ones that matter most.
 */
export default function NightEvents({ rec }) {
  const [showAll, setShowAll] = useState(false)
  const shown = showAll ? rec.events : rec.events.slice(0, FIRST_EVENTS)

  return (
    <Card className="flex flex-col gap-3 shadow-sm">
      <h2 className="text-lg font-medium">Events in the city</h2>
      {rec.eventsSource === 'missing' ? (
        <p className="text-sm text-stone-500">Events not loaded for this night</p>
      ) : rec.events.length === 0 ? (
        <p className="text-sm text-stone-500">No events this night</p>
      ) : (
        <ul className="divide-y divide-stone-100">
          {shown.map((e) => (
            <li key={e.id} className="py-2 first:pt-0 last:pb-0">
              <p className="text-sm font-medium">{e.title}</p>
              <p className="text-xs text-stone-500">
                {[e.venue, e.dayCount > 1 && `Day ${e.dayNumber} of ${e.dayCount}`].filter(Boolean).join(' · ')}
              </p>
            </li>
          ))}
        </ul>
      )}
      {rec.eventsSource !== 'missing' && rec.events.length > FIRST_EVENTS && (
        <Button variant="ghost" size="sm" className="self-start" onClick={() => setShowAll(!showAll)}>
          {showAll ? 'Show fewer' : `Show all ${rec.events.length} events`}
        </Button>
      )}
    </Card>
  )
}
