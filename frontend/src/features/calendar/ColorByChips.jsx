import Chip from '../../components/ui/Chip.jsx'
import { COLOR_MODES } from './colorModes.js'

/** The "Color by" row: one chip per mode in COLOR_MODES; disabled ones say why on hover. */
export default function ColorByChips({ value, onChange }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="mr-1 text-sm text-stone-600">Color by</span>
      {COLOR_MODES.map((mode) => (
        <Chip
          key={mode.id}
          selected={value === mode.id}
          disabled={Boolean(mode.disabled)}
          title={mode.disabled}
          onClick={() => onChange(mode.id)}
        >
          {mode.label}
        </Chip>
      ))}
    </div>
  )
}
