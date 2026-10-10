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

async function request(path, options = {}) {
  const response = await fetch(url(path), { ...options, headers: headers(options.headers) })

  if (response.status === 401) {
    // The token is gone or expired. Drop it so the app falls back to the
    // login screen instead of retrying forever with a token that cannot work.
    clearAccessToken()
    throw new ApiError(401, 'Session expired')
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      if (body?.detail) detail = body.detail
    } catch {
      // A non-JSON error body: keep the status-based message.
    }
    throw new ApiError(response.status, detail)
  }

  return response.status === 204 ? null : response.json()
}

export const api = {
  login: (email, password) =>
    request('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  me: () => request('/auth/me'),
  logout: () => request('/auth/logout', { method: 'POST' }),

  models: () => request('/models'),
  conversations: () => request('/conversations'),
  createConversation: () => request('/conversations', { method: 'POST' }),
  deleteConversation: (id) => request(`/conversations/${id}`, { method: 'DELETE' }),
  messages: (id) => request(`/conversations/${id}/messages`),
  evaluationCallStart: (body) => request('/evaluation-calls/start', { method: 'POST', body: JSON.stringify(body) }),
  evaluationTurn: (id, text) => request(`/evaluation-calls/${id}/turn`, { method: 'POST', body: JSON.stringify({ text }) }),
  evaluationCallEnd: (id) => request(`/evaluation-calls/${id}/end`, { method: 'POST' }),
  evaluationCallBrief: (id) => request(`/evaluation-calls/${id}/brief`),
  evaluationCapabilities: () => request('/evaluation-calls/capabilities'),
  evaluationCallStatuses: () => request('/evaluation-calls/statuses'),
  reconcileEvaluationCall: (id, reason) => request(`/evaluation-calls/${id}/reconcile`, { method: 'POST', body: JSON.stringify({ reason }) }),
  endConversationCall: (id) => request(`/conversations/${id}/end`, { method: 'POST' }),
  evaluationGaps: () => request('/evaluation-gaps'),
  approvedEvaluationGaps: () => request('/evaluation-gaps/approved'),
  submitEvaluationGap: (body) => request('/evaluation-gaps/signals', { method: 'POST', body: JSON.stringify(body) }),
  editEvaluationGap: (id, body) => request(`/evaluation-gaps/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  approveEvaluationGap: (id, reason) => request(`/evaluation-gaps/${id}/approve`, { method: 'POST', body: JSON.stringify({ reason }) }),
  rejectEvaluationGap: (id, reason) => request(`/evaluation-gaps/${id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) }),
  produceEvaluationGaps: (id) => request(`/evaluation-gaps/produce/${id}`, { method: 'POST' }),
  compareEvaluationRounds: (r0, r1) => request('/evaluation-gaps/compare', { method: 'POST', body: JSON.stringify({ r0_call_id: r0, r1_call_id: r1 }) }),
  runEvaluationPair: (body) => request('/evaluation-gaps/run-pair', { method: 'POST', body: JSON.stringify(body) }),
}

// Send one turn and read the Server-Sent Events the backend replies with.
//
// `fetch` is used rather than EventSource because EventSource cannot send a
// POST body or an Authorization header. The frames are parsed by hand, which
// is a few lines: one event is a run of "event:"/"data:" lines ending in a
// blank line.
export async function sendMessage(conversationId, body, handlers) {
  const response = await fetch(url(`/conversations/${conversationId}/messages`), {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify(body),
  })

  if (!response.ok || !response.body) {
    if (response.status === 401) clearAccessToken()
    throw new ApiError(response.status, `Could not reach the agent (${response.status})`)
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
