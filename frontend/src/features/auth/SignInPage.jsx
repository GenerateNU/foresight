import { GOOGLE_SIGN_IN_URL } from '../../api/auth.js'
import ellipseInner from '../../assets/sign-in/ellipse-inner.svg'
import ellipseOuter from '../../assets/sign-in/ellipse-outer.svg'
import googleIcon from '../../assets/sign-in/google.svg'
import logoMark from '../../assets/sign-in/logo-mark.svg'
import Button from '../../components/ui/Button.jsx'

const BRAND_GRADIENT =
  'linear-gradient(140.6deg, var(--color-brand-panel-1) 0%, var(--color-brand-panel-2) 36.5%, var(--color-sky-600) 72%, var(--color-brand-panel-4) 90%)'

/**
 * Sign in, from the Figma "Log in" frame. Google is the only way in, so the design's email,
 * password, "Forgot password?" and "Create an account" aren't built. The button is a plain
 * link to the API, which sends the browser to Google and back (see api/auth.js).
 */
export default function SignInPage() {
  return (
    <div className="flex min-h-screen bg-white">
      <BrandPanel />
      <main className="flex w-full flex-col justify-center gap-6 px-8 shadow-2xl md:w-140 md:shrink-0 md:px-20">
        <div className="space-y-2">
          <h1 className="text-3xl font-medium tracking-tight text-stone-900">Welcome back</h1>
          <p className="text-base text-stone-600">Log in to review tonight's rates.</p>
        </div>
        <Button href={GOOGLE_SIGN_IN_URL} className="w-full font-normal">
          <img src={googleIcon} alt="" width="18" height="18" />
          Continue with Google
        </Button>
      </main>
    </div>
  )
}

/** The left half: logo, headline and the gradient with its two soft circles. Hidden on small screens. */
function BrandPanel() {
  return (
    <section
      className="relative hidden min-w-0 flex-1 overflow-hidden text-white md:block"
      style={{ backgroundImage: BRAND_GRADIENT }}
    >
      <img
        src={ellipseOuter}
        alt=""
        width="1298"
        height="1335"
        className="pointer-events-none absolute top-[-396px] left-[-408px] max-w-none -rotate-[55.25deg]"
      />
      <img
        src={ellipseInner}
        alt=""
        width="825"
        height="814"
        className="pointer-events-none absolute top-[-282px] left-[-200px] max-w-none -rotate-[55.25deg]"
      />

      <div className="relative flex min-h-screen flex-col justify-between px-16 pt-20 pb-16">
        <div className="flex items-center gap-2">
          <img src={logoMark} alt="" width="22" height="22" />
          <span className="font-display text-4xl font-medium tracking-tight">foresight</span>
        </div>
        <div className="max-w-188 space-y-4">
          <p className="font-display text-6xl leading-[1.1] font-medium tracking-[-1.2px]">
            See the busy nights before your guests do.
          </p>
          <p className="max-w-115 text-lg leading-[1.6]">
            Foresight reads Dublin's events overnight and keeps your rates in step with demand.
          </p>
        </div>
        <p className="text-xs">© 2026 Foresight</p>
      </div>
    </section>
  )
}
