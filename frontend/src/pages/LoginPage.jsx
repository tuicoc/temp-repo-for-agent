// The sign-in screen.
//
// There is no "create account" half. One account is seeded from the server's
// environment, and the page exists so that a public URL is not a free LLM
// bill — not to manage identities.

import { useState } from 'react'
import { useAuth } from '../context/AuthContext'

const inputClass =
  'w-full rounded-xl border border-app-border bg-white px-3.5 py-2.5 text-[14px] ' +
  'text-app-dark placeholder:text-app-muted/70 outline-none transition ' +
  'focus:border-app-accent focus:shadow-input'

export function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const { login, busy, error, clearError } = useAuth()

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
    <div className="flex min-h-full items-center justify-center px-4">
      <div className="w-full max-w-[380px]">
        <div className="mb-8 flex flex-col items-center">
          <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-2xl bg-app-accent shadow-sm">
            <span className="text-lg font-semibold text-white">A</span>
          </div>
          <h1 className="text-[22px] font-semibold text-app-dark">Welcome back</h1>
          <p className="mt-1 text-[13px] text-app-muted">Sign in to continue</p>
        </div>

        <div className="rounded-2xl border border-app-border bg-app-surface p-6 shadow-sm">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="email" className="mb-1.5 block text-[12px] font-medium text-app-body">
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
              <label htmlFor="password" className="mb-1.5 block text-[12px] font-medium text-app-body">
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
              <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-[12px] text-red-700">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={busy}
              className="flex w-full items-center justify-center rounded-xl bg-app-accent py-2.5 text-[14px]
                         font-medium text-white transition hover:brightness-95 disabled:opacity-60"
            >
              {busy ? (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
              ) : (
                'Sign in'
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
