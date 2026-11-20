import { createContext, useContext } from 'react'

/** Filled by AuthProvider; read it with useAuth(). */
export const AuthContext = createContext(null)

/**
 * The signed-in user, from AuthProvider: `{ user, hotels, hotel, status, retry }`.
 * `status` is 'loading' | 'authed' | 'anon' | 'no-hotel' | 'error'. `hotel` is the first
 * of `hotels`: a user works for one hotel for now. `retry` asks /auth/me again.
 */
export function useAuth() {
  const auth = useContext(AuthContext)
  if (!auth) throw new Error('useAuth() needs an <AuthProvider> above it')
  return auth
}
