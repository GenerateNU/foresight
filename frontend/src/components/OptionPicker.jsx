// A titled row of buttons where exactly one option is selected.
// options: [{ id, label, delta }]
function OptionPicker({ title, source, options, value, onChange }) {
  return (
    <div className="control">
      <h2 className="control-title">
        {title} {source && <span className="source">{source}</span>}
      </h2>
      <div className="option-grid" style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}>
        {options.map((option) => {
          const selected = option.id === value
          return (
            <button
              key={option.id}
              className={selected ? 'option option-selected' : 'option'}
              aria-pressed={selected}
              onClick={() => onChange(option.id)}
            >
              <span className="option-label">{option.label}</span>
              <span className="option-delta">{option.delta}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

export default OptionPicker
