import { useEffect } from 'react'
import { Navigate } from 'react-router-dom'
import { clearReturnPath, readReturnPath } from '../../api/auth.js'

/**
 * The app's root. After sign-in the API always lands here, so go back to the page saved
 * before the redirect, or to the calendar.
 */
export default function ReturnAfterSignIn() {
  // Read during render and clear in an effect, so StrictMode's double render sees the path.
  const path = readReturnPath() ?? '/calendar'
  useEffect(clearReturnPath, [])
  return <Navigate to={path} replace />
}
