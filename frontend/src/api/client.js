import { API_URL, USE_MOCKS } from '../lib/config.js'
import { saveReturnPath } from './auth.js'

const SIGN_IN_PATH = '/sign-in'

/** A failed API call: `status` is the HTTP status, `message` is readable. */
export class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

/**
 * GET `path` from the API with `params` as the query string, and return the JSON body.
 * The only code that talks HTTP: everything else calls the functions in src/api/*, so
 * auth, retries or error handling change here and nowhere else.
 */
export async function apiGet(path, params = {}) {
  if (USE_MOCKS) {
    // Loaded on demand, so a real build never downloads the mocks.
    const { mockGet } = await import('./mocks/index.js')
    return mockGet(path, params)
  }

  const url = new URL(path, API_URL)
  for (const [key, value] of Object.entries(params)) {
    if (value != null) url.searchParams.set(key, value)
  }

  // `include` sends the session cookie to the API, which lives on another origin.
  const response = await fetch(url, { credentials: 'include' })
  if (response.status === 401) redirectToSignIn()
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new ApiError(response.status, readableDetail(body.detail) ?? response.statusText)
  }
  return response.json()
}

/** FastAPI's `detail` is a string for most errors, but a list of field problems for a 422. */
function readableDetail(detail) {
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join('; ')
  return detail
}

/** Not signed in (or the session expired): go to sign in, then come back here after. */
function redirectToSignIn() {
  const { pathname, search } = window.location
  if (pathname === SIGN_IN_PATH) return
  saveReturnPath(pathname + search)
  window.location.assign(SIGN_IN_PATH)
}
