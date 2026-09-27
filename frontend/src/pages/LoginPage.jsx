// The sign-in screen.
//
// There is no "create account" half. One account is seeded from the server's
// environment, and the page exists so that a public URL is not a free LLM
// bill — not to manage identities.

import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { Button } from '../components/ui'

const inputClass =
  'w-full rounded-md border border-line bg-white px-3.5 py-2.5 text-[14px] ' +
  'text-ink placeholder:text-faint outline-none transition ' +
  'focus:border-accent focus:shadow-input'

export function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const { login, busy, error, clearError } = useAuth()
  const [signup, setSignup] = useState(false)

  if (signup) return <SignUp onBack={() => setSignup(false)} />

  async function handleSubmit(event) {
    event.preventDefault()
    if (busy) return
    try {
      await login(email, password)
    } catch {
      // The message is already in the context and rendered below.
    }
  }

  function onChange(setter) {
    return (event) => {
      clearError()
      setter(event.target.value)
    }
  }

  return (
    <div className="flex h-full items-center justify-center bg-surface px-4">
      <div className="w-full max-w-[380px]">
        <div className="mb-8 flex flex-col items-center">
          <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-accent">
            <span className="text-lg font-semibold text-white">A</span>
          </div>
          <h1 className="text-[20px] font-semibold text-ink">Agent Core</h1>
          <p className="mt-1 text-[13px] text-muted">Sign in to continue</p>
        </div>

        <div className="rounded-lg border border-line bg-surface p-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="email" className="mb-1.5 block text-[12px] font-medium text-muted">
                Email address
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={onChange(setEmail)}
                placeholder="you@example.com"
                required
                autoComplete="email"
                className={inputClass}
              />
            </div>

            <div>
              <label htmlFor="password" className="mb-1.5 block text-[12px] font-medium text-muted">
                Password
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={onChange(setPassword)}
                required
                autoComplete="current-password"
                className={inputClass}
              />
            </div>

            {error && (
              <p role="alert" className="border-l-2 border-danger pl-3 text-[12.5px] text-ink">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={busy}
              className="flex w-full items-center justify-center rounded-lg bg-accent py-2.5 text-[14px]
                         font-medium text-white transition-colors hover:bg-[#274d73] disabled:opacity-60"
            >
              {busy ? (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
              ) : (
                'Sign in'
              )}
            </button>
          </form>
        </div>

        <p className="mt-5 text-center text-[13px] text-muted">
          No account?{' '}
          <button type="button" onClick={() => setSignup(true)} className="text-accent hover:underline">Sign up</button>
        </p>
      </div>
    </div>
  )
}

// The sign-up that isn't. The deposit screen keeps a straight face, so the
// punchline lands while the spinner is still turning. No field asks for
// anything, and nothing is ever charged.
function SignUp({ onBack }) {
  const [step, setStep] = useState('offer')

  useEffect(() => {
    if (step !== 'paying') return
    const timer = setTimeout(() => setStep('kidding'), 1600)
    return () => clearTimeout(timer)
  }, [step])

  return (
    <div className="flex h-full items-center justify-center bg-surface px-4">
      <div className="w-full max-w-[380px] text-center">
        {step === 'offer' && (
          <>
            <h1 className="text-[20px] font-semibold text-ink">Create an account</h1>
            <p className="mt-2 text-[13px] text-muted">A one-time deposit is required to open an account.</p>
            <div className="mt-6 rounded-lg border border-line p-6 text-left">
              <div className="flex items-baseline justify-between">
                <span className="text-[13px] text-muted">Account deposit</span>
                <span className="text-[24px] font-semibold leading-none text-ink">$1.99</span>
              </div>
              <ul className="mt-4 space-y-1.5 text-[12.5px] text-muted">
                <li>Charged once, when the account is approved.</li>
                <li>Refunded in full if the account is not approved.</li>
                <li>Secure payment, no card details stored.</li>
              </ul>
              <Button variant="primary" className="mt-5 w-full justify-center" onClick={() => setStep('paying')}>Pay $1.99 and continue</Button>
            </div>
            <button type="button" onClick={onBack} className="mt-5 text-[13px] text-muted hover:text-ink">Back to sign in</button>
          </>
        )}
        {(step === 'paying' || step === 'kidding') && (
          <div className="flex flex-col items-center">
            <span className="mb-5 h-7 w-7 animate-spin rounded-full border-2 border-line border-t-accent" />
            {step === 'paying' ? (
              <div className="text-[14px] text-ink">Processing your payment</div>
            ) : (
              <>
                <div className="text-[18px] font-semibold text-ink">Just kidding, we do not support this feature yet =))</div>
                <p className="mt-2 text-[13px] text-muted">Nothing was charged. Ask the team for an account instead.</p>
                <Button variant="primary" className="mt-6" onClick={onBack}>Back to sign in</Button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
