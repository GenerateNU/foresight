import { useState } from 'react'
import { signOut } from '../../api/auth.js'
import Button from '../../components/ui/Button.jsx'

/**
 * Ends the session, then loads the sign-in page fresh so nothing from it is left behind.
 * `variant` and `className` go to the Button.
 */
export default function SignOutButton({ variant, className }) {
  const [busy, setBusy] = useState(false)

  async function handleClick() {
    setBusy(true)
    try {
      await signOut()
    } finally {
      window.location.assign('/sign-in')
    }
  }

  return (
    <Button variant={variant} onClick={handleClick} disabled={busy} className={className}>
      Sign out
    </Button>
  )
}
