import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Runs `run` whenever `key` changes and returns `{ data, error, loading, reload }`.
 * `key` is a string that identifies "what we're asking for", e.g. "2026-10-01:2026-11-08".
 * A result only counts if it belongs to the CURRENT request, which also stops a slow old
 * response from overwriting a newer one when the user clicks through months quickly.
 * `reload()` runs it again for the same key, e.g. from ErrorState's "Try again".
 */
export function useAsync(key, run) {
  const [result, setResult] = useState({ request: null, data: null, error: null })
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
      .then((data) => !cancelled && setResult({ request, data, error: null }))
      .catch((error) => !cancelled && setResult({ request, data: null, error }))
    return () => {
      cancelled = true
    }
  }, [request])

  const reload = useCallback(() => setAttempt((n) => n + 1), [])
  const current = result.request === request
  return {
    data: current ? result.data : null,
    error: current ? result.error : null,
    loading: !current,
    reload,
  }
}
