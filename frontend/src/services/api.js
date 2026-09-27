// Every call to the backend goes through here.
//
// The backend is deployed separately, so its origin comes from the build. Left
// blank, calls stay relative and Vite's dev proxy forwards them, which keeps
// development free of CORS. Set VITE_API_BASE_URL for a real deployment; the
// server must list that page's origin in CORS_ORIGINS or the browser will
// refuse every call before it leaves.

import { getAccessToken, clearAccessToken } from './tokenStore'

const BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

const url = (path) => `${BASE}/api${path}`

class ApiError extends Error {
  constructor(status, detail) {
    super(detail)
    this.status = status
  }
}

function headers(extra = {}) {
  const token = getAccessToken()
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  }
}

async function detailOf(response, fallback) {
  try {
    const body = await response.json()
    if (body?.detail) return typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
  } catch {
    // A non-JSON error body: keep the status-based message.
  }
  return fallback
}

async function request(path, options = {}) {
  const response = await fetch(url(path), { ...options, headers: headers(options.headers) })

  if (response.status === 401) {
    // The token is gone or expired. Drop it so the app falls back to the
    // login screen instead of retrying forever with a token that cannot work.
    clearAccessToken()
    throw new ApiError(401, 'Session expired')
  }

  if (!response.ok) {
    throw new ApiError(response.status, await detailOf(response, `Request failed (${response.status})`))
  }

  return response.status === 204 ? null : response.json()
}

export const api = {
  login: (email, password) =>
    request('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  me: () => request('/auth/me'),
  logout: () => request('/auth/logout', { method: 'POST' }),

  // A call is placed on a channel — web, zalo (with its account) or hotline
  // (with the number it comes from) — and hung up.
  startCall: (body) => request('/calls', { method: 'POST', body: JSON.stringify(body) }),
  endCall: (id) => request(`/calls/${id}/end`, { method: 'POST' }),
  calls: (openOnly = false) => request(`/calls?open_only=${openOnly}`),
  call: (id) => request(`/calls/${id}`),

  // Handoff and copilot. The customer asks for a person; a consultant
  // accepts; from then on the assistant drafts and the consultant sends.
  requestHandoff: (id, reason) =>
    request(`/calls/${id}/handoff`, { method: 'POST', body: JSON.stringify({ reason: reason ?? null }) }),
  acceptHandoff: (id) => request(`/calls/${id}/accept`, { method: 'POST' }),
  // The consultant's words pass the guard: { sent, warnings, call }. Sending
  // anyway after a warning is `force`.
  reply: (id, content, action, force = false) =>
    request(`/calls/${id}/reply`, { method: 'POST', body: JSON.stringify({ content, action, force }) }),
  // The Gap Loop: the consultant's answer saved as a FAQ entry.
  saveFaq: (id, question, answer) =>
    request(`/calls/${id}/faq`, { method: 'POST', body: JSON.stringify({ question, answer }) }),

  health: () => fetch('/health').then((r) => r.json()),

  // Admin: what this process runs on. A restart returns to config/models.yaml.
  advisorSettings: () => request('/admin/advisor'),
  setAdvisor: (body) => request('/admin/advisor', { method: 'POST', body: JSON.stringify(body) }),
  voiceSettings: () => request('/admin/voice'),
  setVoice: (body) => request('/admin/voice', { method: 'POST', body: JSON.stringify(body) }),
  warmVoice: () => request('/admin/voice/warm', { method: 'POST' }),
  clock: () => request('/admin/clock'),
  setClock: (day) => request('/admin/clock', { method: 'POST', body: JSON.stringify({ day }) }),
  latency: (channel = 'all') => request(`/admin/latency?channel=${channel}`),
}

// Send one turn of a call and read the Server-Sent Events the backend replies
// with. A body without `content` is the pickup: the agent speaks first.
//
// `fetch` is used rather than EventSource because EventSource cannot send a
// POST body or an Authorization header. The frames are parsed by hand, which
// is a few lines: one event is a run of "event:"/"data:" lines ending in a
// blank line. A comment line (": keepalive") has no data and is dropped.
export async function sendTurn(callId, body, handlers) {
  const response = await fetch(url(`/calls/${callId}/turn`), {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify(body),
  })

  if (!response.ok || !response.body) {
    if (response.status === 401) clearAccessToken()
    throw new ApiError(
      response.status,
      await detailOf(response, `Could not reach the agent (${response.status})`),
    )
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let split
    while ((split = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, split)
      buffer = buffer.slice(split + 2)

      let event = 'message'
      let data = ''
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (!data) continue

      try {
        handlers[event]?.(JSON.parse(data))
      } catch {
        // A frame we cannot parse is dropped rather than killing the stream.
      }
    }
  }
}
