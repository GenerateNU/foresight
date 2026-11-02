import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Runs `run` whenever `key` changes and returns `{ data, error, loading, refreshing, reload }`.
 * `key` is a string that identifies "what we're asking for", e.g. "2026-10-01:2026-11-08".
 * A result only counts if it belongs to the CURRENT request, which also stops a slow old
 * response from overwriting a newer one when the user clicks through months quickly.
 * `reload()` runs it again for the same key, e.g. from ErrorState's "Try again" or after a
 * save. While it does, the last data stays in `data` and `refreshing` is true, so the
 * screen can keep it on show (docs/decisions/0041). `loading` means nothing to show yet.
 */
export function useAsync(key, run) {
  const [result, setResult] = useState({ key: null, request: null, data: null, error: null })
  const [attempt, setAttempt] = useState(0)
  const runRef = useRef(run)
  const request = `${key}#${attempt}`

  useEffect(() => {
    runRef.current = run
  })

  useEffect(() => {
    let cancelled = false
    runRef
      .current()
      .then((data) => !cancelled && setResult({ key, request, data, error: null }))
      .catch((error) => !cancelled && setResult({ key, request, data: null, error }))
    return () => {
      cancelled = true
    }
  }, [key, request])

  const reload = useCallback(() => setAttempt((n) => n + 1), [])
  const current = result.request === request
  // Data for the same key is still right to show while it reloads; another key's isn't.
  const data = result.key === key ? result.data : null
  return {
    data,
    error: current ? result.error : null,
    loading: !current && data == null,
    refreshing: !current && data != null,
    reload,
  }
}
