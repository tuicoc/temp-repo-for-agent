// The access token, kept in localStorage so a page reload does not log you out.
//
// The reference project keeps its token in memory only and restores it from an
// HttpOnly refresh cookie, which is safer: a token in localStorage is readable
// by any script that runs on the page. We do not have a refresh cookie, so the
// choice here is between storing it and logging the user out on every reload.
//
// This is acceptable while one seeded account signs in to a demo. It stops
// being acceptable when real customers have accounts, and the fix then is to
// bring over the refresh-cookie flow rather than to harden this file.

const KEY = 'agent-core.token'

export function setAccessToken(token) {
  try {
    localStorage.setItem(KEY, token)
  } catch {
    // Private browsing, or storage disabled. The session still works until
    // the page is reloaded, which is better than refusing to sign in.
  }
}

export function getAccessToken() {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

export function clearAccessToken() {
  try {
    localStorage.removeItem(KEY)
  } catch {
    // Nothing to clear if it was never stored.
  }
}
