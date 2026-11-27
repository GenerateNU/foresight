import { useId, useState } from 'react'
import pencil from '../../assets/night/pencil.svg'
import Button from '../../components/ui/Button.jsx'
import Card from '../../components/ui/Card.jsx'

/**
 * The manager's own rate for the night: an editable pill, starting at their last rate or
 * ours, and Save, which calls `onSave(rate)` and shows its error if it fails. A past
 * night has no snapshot to give feedback on, so it can't be saved.
 */
export default function YourRate({ rec, onSave }) {
  const id = useId()
  const [draft, setDraft] = useState(String(Math.round(rec.managerRate ?? rec.rate)))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const rate = Number(draft)
  const valid = draft.trim() !== '' && Number.isFinite(rate) && rate > 0
  const canSave = valid && rec.snapshotId != null && !saving

  async function save(event) {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await onSave(rate)
    } catch (err) {
      setError(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card className="flex flex-col gap-3 shadow-sm">
      <div>
        <h2 className="text-lg font-medium">Your rate</h2>
        <p className="text-xs text-stone-500">
          {rec.snapshotId == null
            ? "Past nights can't take a new rate."
            : 'Your own rate for this night, before VAT.'}
        </p>
      </div>

      <form onSubmit={save} className="flex items-center gap-3">
        <label htmlFor={id} className="text-sm font-medium">
          Your rate
        </label>
        <div className="flex h-8 w-28 items-center gap-1 rounded-control border border-stone-200 bg-white px-3 focus-within:ring-2 focus-within:ring-sky-400">
          <span className="text-sm font-medium">€</span>
          <input
            id={id}
            inputMode="decimal"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={rec.snapshotId == null}
            aria-invalid={!valid}
            className="w-full min-w-0 bg-transparent text-sm font-medium focus:outline-none"
          />
          <img src={pencil} alt="" width="14" height="14" />
        </div>
        <Button type="submit" variant="primary" size="sm" disabled={!canSave}>
          {saving ? 'Saving…' : 'Save'}
        </Button>
      </form>

      {error && (
        <p role="alert" className="text-xs text-error-600">
          Couldn't save: {error.message}
        </p>
      )}
    </Card>
  )
}
