// Who is signed in, and the two operations that change it.
//
// The token lives in tokenStore; this context only decides what the app shows.
// On mount it asks the server who the stored token belongs to, so a token that
// expired while the tab was closed lands on the login screen rather than on a
// chat page that fails on its first request.

import { createContext, useContext, useEffect, useState } from 'react'
import { api } from '../services/api'
import { endRememberedSession } from '../services/session'
import { setAccessToken, getAccessToken, clearAccessToken } from '../services/tokenStore'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [restoring, setRestoring] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!getAccessToken()) {
      setRestoring(false)
      return
    }
    api
      .me()
      .then(setUser)
      .catch(() => clearAccessToken())
      .finally(() => setRestoring(false))
  }, [])

  async function login(email, password) {
    setBusy(true)
    setError('')
    try {
      const result = await api.login(email, password)
      setAccessToken(result.access_token)
      setUser(await api.me())
    } catch (err) {
      setError(err.message || 'Could not sign in')
      throw err
    } finally {
      setBusy(false)
    }
  }

  async function logout() {
    // A customer who signs out has left: their chat session ends with them.
    await endRememberedSession()
    try {
      await api.logout()
    } catch {
      // The server keeps no session, so a failed call changes nothing here.
    }
    clearAccessToken()
    setUser(null)
  }

  return (
    <AuthContext.Provider
      value={{ user, restoring, error, busy, login, logout, clearError: () => setError('') }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
