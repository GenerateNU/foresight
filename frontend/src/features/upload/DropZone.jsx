import { useId, useState } from 'react'
import { cx } from '../../lib/cx.js'
import { MAX_FILE_MB, MAX_FILES, REPORTS } from './uploadUtils.js'

/**
 * Where files go in: drop them on it, or click to pick. Calls `onFiles(files)` with what
 * was dropped or picked; checking them is the page's job.
 */
export default function DropZone({ onFiles, disabled = false }) {
  const id = useId()
  const [over, setOver] = useState(false)

  function drop(event) {
    event.preventDefault()
    setOver(false)
    if (!disabled) onFiles([...event.dataTransfer.files])
  }

  return (
    <label
      htmlFor={id}
      onDragOver={(e) => {
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
      className={cx(
        'flex cursor-pointer flex-col items-center gap-2 rounded-card border border-dashed px-6 py-12 text-center transition-colors',
        over ? 'border-sky-400 bg-sky-50' : 'border-stone-200 bg-white hover:bg-stone-25',
        disabled && 'cursor-not-allowed opacity-40',
      )}
    >
      <p className="text-base font-medium">Drop the day's Guestline exports here</p>
      <p className="text-sm text-stone-500">or click to choose files</p>
      <p className="text-xs text-stone-500">
        {REPORTS.join(' and ')}, as CSV. Up to {MAX_FILES} files, {MAX_FILE_MB} MB each.
      </p>
      <input
        id={id}
        type="file"
        accept=".csv,text/csv"
        multiple
        disabled={disabled}
        className="sr-only"
        onChange={(e) => {
          onFiles([...e.target.files])
          e.target.value = ''
        }}
      />
    </label>
  )
}
