import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { saveReturnPath } from '../../api/auth.js'
import EmptyState from '../../components/ui/EmptyState.jsx'
import ErrorState from '../../components/ui/ErrorState.jsx'
import LoadingState from '../../components/ui/LoadingState.jsx'
import SignOutButton from './SignOutButton.jsx'
import { useAuth } from './useAuth.js'

/**
 * Wraps every signed-in route. Shows the page only once /auth/me says who's signed in and
 * which hotel they work for; otherwise a full-screen state. These states have no Figma
 * design yet, so they use the shared loading, empty and error states.
 */
export default function RequireAuth() {
  const { status, retry } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return (
      <FullScreen>
        <LoadingState label="Checking your sign-in…" />
      </FullScreen>
    )
  }

  if (status === 'anon') {
    // The root already goes to the calendar after sign-in; saving it would send it back to itself.
    if (location.pathname !== '/') saveReturnPath(location.pathname + location.search)
    return <Navigate to="/sign-in" replace />
  }

  if (status === 'no-hotel') {
    return (
      <FullScreen>
        <EmptyState title="No hotel linked to your account" action={<SignOutButton />} />
      </FullScreen>
    )
  }

  if (status === 'error') {
    return (
      <FullScreen>
        <ErrorState title="Couldn't reach Foresight. Check your connection." onRetry={retry} />
      </FullScreen>
    )
  }

  return <Outlet />
}

function FullScreen({ children }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-stone-25 px-4">
      <div className="w-full max-w-md">{children}</div>
    </main>
  )
}
