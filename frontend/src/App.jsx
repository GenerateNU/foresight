import { useState } from 'react'
import logo from './assets/foresight-logo.svg'
import OptionPicker from './components/OptionPicker'
import Events from './components/Events'
import PriceBreakdown from './components/PriceBreakdown'
import { DAYS, DAY_ADJ, FLIGHTS, FULL_DAY, WEATHER, priceFactors, signed } from './pricing'
import './App.css'

const STEPS = ['Signals come in', 'Learns from history', 'Explains its price', 'Manager approves']

// The starting state, also used by the Reset button.
function initialState() {
  return {
    day: 'Sat',
    weather: 'Rain',
    flights: 'More',
    approved: false,
    nextId: 3,
    events: [
      { id: 1, title: 'Concert at Gillette', category: 'concert', day: 'Sat', attendance: 65000 },
      { id: 2, title: 'Second Gillette show', category: 'concert', day: 'Sun', attendance: 65000 },
    ],
  }
}

function App() {
  const [state, setState] = useState(initialState)
  // Changing this number gives the Events form a fresh start on Reset.
  const [resetCount, setResetCount] = useState(0)

  // Any change to the inputs means the price has to be approved again.
  function update(changes) {
    setState({ ...state, ...changes, approved: false })
  }

  function reset() {
    setState(initialState())
    setResetCount(resetCount + 1)
  }

  function addEvent(event) {
    update({ events: [...state.events, { ...event, id: state.nextId }], nextId: state.nextId + 1 })
  }

  function removeEvent(id) {
    update({ events: state.events.filter((e) => e.id !== id) })
  }

  const dayOptions = DAYS.map((d) => ({ id: d, label: d, delta: signed(DAY_ADJ[d]) }))
  const weatherOptions = WEATHER.map((w) => ({ id: w.id, label: w.id, delta: signed(w.adj) }))
  const flightOptions = FLIGHTS.map((f) => ({ id: f.id, label: f.id, delta: signed(f.adj) }))

  return (
    <>
      <header className="header">
        <img src={logo} alt="Foresight" width="120" />
        <div className="header-right">
          <span className="example-label">example numbers</span>
          <button className="button-outline" onClick={reset}>Reset</button>
        </div>
      </header>

      <main className="main">
        <div className="steps">
          {STEPS.map((step, i) => (
            <span key={step} className="step-group">
              {i > 0 && <span className="arrow" aria-hidden="true">→</span>}
              <span className="step">{step}</span>
            </span>
          ))}
        </div>

        <div className="columns">
          <section className="controls-column">
            <OptionPicker
              title="Date"
              options={dayOptions}
              value={state.day}
              onChange={(day) => update({ day })}
            />
            <OptionPicker
              title="Weather"
              source="Open-Meteo"
              options={weatherOptions}
              value={state.weather}
              onChange={(weather) => update({ weather })}
            />
            <OptionPicker
              title="Flights"
              source="AeroDataBox"
              options={flightOptions}
              value={state.flights}
              onChange={(flights) => update({ flights })}
            />
            <Events
              key={resetCount}
              events={state.events}
              selectedDay={state.day}
              onAdd={addEvent}
              onRemove={removeEvent}
            />
          </section>

          <PriceBreakdown
            factors={priceFactors(state)}
            dayName={FULL_DAY[state.day]}
            approved={state.approved}
            onApprove={() => setState({ ...state, approved: true })}
          />
        </div>

        <div className="footnote">
          Explainable Boosting Machine (InterpretML). Every factor's effect on the price is visible.
        </div>
      </main>
    </>
  )
}

export default App
