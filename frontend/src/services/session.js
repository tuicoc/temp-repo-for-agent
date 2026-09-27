// The customer's current chat session, remembered by this browser.
//
// A session should survive leaving the page and coming back: navigating to
// another screen and returning must not start a second conversation. It
// ends when the customer ends it, when they sign out, or when the server
// finds it idle. The id is a per-browser convenience, so it lives in
// localStorage and every access is guarded — storage can be absent, and
// the server is the source of truth for whether the session is still open.

import { api } from './api'

const KEY = 'agent-core.chat-session'

export function getSessionId() {
  try {
    const value = localStorage.getItem(KEY)
    return value ? Number(value) : null
  } catch {
    return null
  }
}

export function setSessionId(id) {
  try {
    localStorage.setItem(KEY, String(id))
  } catch {
    // Storage is unavailable; the session still works until the page reloads.
  }
}

export function clearSessionId() {
  try {
    localStorage.removeItem(KEY)
  } catch {
    // Nothing to clear.
  }
}

// Resume the remembered session if the server still has it open; otherwise
// forget it. Returns the session, with its turns, or null.
export async function resumeSession() {
  const id = getSessionId()
  if (id == null) return null
  try {
    const session = await api.call(id)
    if (session.ended_at) {
      clearSessionId()
      return null
    }
    return session
  } catch {
    clearSessionId()
    return null
  }
}

// End the remembered session, if any. Called on sign-out, before the token
// goes, so the console does not keep an open session for a customer who left.
export async function endRememberedSession() {
  const id = getSessionId()
  if (id == null) return
  clearSessionId()
  try {
    await api.endCall(id)
  } catch {
    // Already ended, or unreachable; the server's idle sweep covers the rest.
  }
}
