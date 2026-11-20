import { API_URL } from '../lib/config.js'

// Sign-in is a page visit to the API, not a fetch: the API sends the browser to Google, and
// Google sends it back to the API, which always redirects to the app's root (FRONTEND_URL).
// The API ignores any `next` parameter on purpose (docs/decisions/0040), so the page to come
// back to is kept in sessionStorage instead.

const RETURN_PATH_KEY = 'foresight.returnPath'

/** Where the "Sign in with Google" button goes. */
export const GOOGLE_SIGN_IN_URL = new URL('/auth/google/login', API_URL).href

/** Remember `path` (pathname + search) so the app can go back there after sign-in. */
export function saveReturnPath(path) {
  try {
    sessionStorage.setItem(RETURN_PATH_KEY, path)
  } catch {
    // Storage blocked (e.g. private mode): after sign-in the user lands on the calendar.
  }
}

/** The path saved by `saveReturnPath`, or null. Only same-app paths, never another site. */
export function readReturnPath() {
  try {
    const path = sessionStorage.getItem(RETURN_PATH_KEY)
    return path?.startsWith('/') && !path.startsWith('//') ? path : null
  } catch {
    return null
  }
}

/** Forget the saved path once the app has gone back to it. */
export function clearReturnPath() {
  try {
    sessionStorage.removeItem(RETURN_PATH_KEY)
  } catch {
    // Nothing saved, nothing to clear.
  }
}
