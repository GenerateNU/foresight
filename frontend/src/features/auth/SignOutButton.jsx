import { useState } from 'react'
import { signOut } from '../../api/auth.js'
import Button from '../../components/ui/Button.jsx'

/** Ends the session, then loads the sign-in page fresh so nothing from it is left behind. */
export default function SignOutButton({ className }) {
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
    <Button onClick={handleClick} disabled={busy} className={className}>
      Sign out
    </Button>
  )
}
