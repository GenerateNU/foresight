import { GOOGLE_SIGN_IN_URL } from '../../api/auth.js'
import Button from '../../components/ui/Button.jsx'
import Card from '../../components/ui/Card.jsx'

/** Sign in with Google. A stand-in until the designed page lands (issue #108). */
export default function SignInPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-stone-25 px-4">
      <Card className="w-full max-w-sm space-y-6 text-center">
        <h1 className="font-display text-2xl text-stone-900">Sign in to Foresight</h1>
        <Button variant="primary" href={GOOGLE_SIGN_IN_URL} className="w-full">
          Sign in with Google
        </Button>
      </Card>
    </main>
  )
}
