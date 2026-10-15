import { useState } from 'react'
import { CATEGORIES, DAYS, eventContribution, signed } from '../pricing'

const EMPTY_DRAFT = { title: '', category: 'concert', day: 'Sat', attendance: '20000' }

function Events({ events, selectedDay, onAdd, onRemove }) {
  // What's typed into the form so far. It only becomes an event when "Add event" is clicked.
  const [draft, setDraft] = useState(EMPTY_DRAFT)

  function updateDraft(field, value) {
    setDraft({ ...draft, [field]: value })
  }

  function handleSubmit(e) {
    e.preventDefault()
    onAdd({
      title: draft.title.trim() || 'New event',
      category: draft.category,
      day: draft.day,
      attendance: Math.max(0, Number(draft.attendance) || 0),
    })
    setDraft({ ...draft, title: '' })
  }

  return (
    <div className="control">
      <h2 className="control-title">
        Events <span className="source">PredictHQ</span>
      </h2>

      <div className="event-list">
        {events.map((event) => {
          const active = event.day === selectedDay
          return (
            <div key={event.id} className={active ? 'event-row' : 'event-row event-inactive'}>
              <div className="event-text">
                <span className="event-title">{event.title}</span>
                <span className="event-meta">
                  {event.category} · {event.day} · {event.attendance.toLocaleString('en-US')}
                </span>
              </div>
              <div className="event-actions">
                <span className="event-value">
                  {active ? signed(eventContribution(event)) : 'not on ' + selectedDay}
                </span>
                <button
                  className="icon-button"
                  aria-label={'Remove ' + event.title}
                  onClick={() => onRemove(event.id)}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                    <path d="M6 6l12 12" />
                    <path d="M18 6 6 18" />
                  </svg>
                </button>
              </div>
            </div>
          )
        })}
      </div>

      <form className="event-form" onSubmit={handleSubmit}>
        <span className="event-form-title">Add an event</span>
        <div className="event-form-grid">
          <div className="field field-wide">
            <label htmlFor="ev-title">title</label>
            <input
              id="ev-title"
              type="text"
              placeholder="Concert at Gillette"
              value={draft.title}
              onChange={(e) => updateDraft('title', e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="ev-cat">category</label>
            <select id="ev-cat" value={draft.category} onChange={(e) => updateDraft('category', e.target.value)}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="ev-day">day</label>
            <select id="ev-day" value={draft.day} onChange={(e) => updateDraft('day', e.target.value)}>
              {DAYS.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="ev-att">attendance</label>
            <input
              id="ev-att"
              type="number"
              min="0"
              step="1000"
              value={draft.attendance}
              onChange={(e) => updateDraft('attendance', e.target.value)}
            />
          </div>
          <div className="field-button">
            <button type="submit" className="button-primary button-full">Add event</button>
          </div>
        </div>
      </form>

      <pre className="schema">{`event {
  title        text
  category     concert | sports | festival | conference
  day          Mon .. Sun
  attendance   number
}`}</pre>
    </div>
  )
}

export default Events
