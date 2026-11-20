import { useMemo } from 'react'
import { getMe } from '../../api/auth.js'
import { useAsync } from '../../hooks/useAsync.js'
import { AuthContext } from './useAuth.js'

/**
 * Asks GET /auth/me once and shares the answer with everything below it (see useAuth).
 * A 401 means nobody is signed in; any other failure is an error to retry.
 */
export default function AuthProvider({ children }) {
  const { data: me, error, loading, reload } = useAsync('auth/me', getMe)

  const auth = useMemo(() => {
    const hotels = me?.hotels ?? []
    return {
      user: me,
      hotels,
      hotel: hotels[0] ?? null,
      status: authStatus({ me, error, loading }),
      retry: reload,
    }
  }, [me, error, loading, reload])

  return <AuthContext value={auth}>{children}</AuthContext>
}

function authStatus({ me, error, loading }) {
  if (loading) return 'loading'
  if (error) return error.status === 401 ? 'anon' : 'error'
  return me.hotels.length > 0 ? 'authed' : 'no-hotel'
}
