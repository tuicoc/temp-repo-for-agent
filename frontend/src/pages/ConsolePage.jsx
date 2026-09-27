// The Agent Console: what a consultant works from. Three panes that each
// scroll on their own inside the viewport: the queue, the transcript of the
// selected conversation seen from the staff side, and the evidence behind
// it — the Call Brief the assistant was given at pickup, the context, and
// each assistant turn's tools, confidence and citations.
//
// A conversation is in one of two modes, and the console follows it.
// While the assistant is handling it, the consultant observes: no composer,
// no suggestion, nothing to press. Copilot mode begins only with a handoff —
// the customer asked for a person, or later the assistant decided to hand
// over — and after a consultant has accepted it. Then the assistant drafts
// a reply to each customer message and the consultant sends: as written,
// edited, or their own words.
//
// Live updates are slow polling: the queue every five seconds, the open
// conversation every three.
//
// What the consultant sends passes the same guard as the assistant's drafts
// (docs/design.md section 4.6): a violation comes back as a warning to send
// anyway or fix. After answering a handed-over question, the consultant may
// save the answer as a FAQ entry, live at once (the Gap Loop, section 10.2).

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../services/api'
import { useAuth } from '../context/AuthContext'
import { MessageBubble } from '../components/MessageBubble'
import { Button, Notice, Tag } from '../components/ui'

const QUEUE_EVERY_MS = 5000
const TRANSCRIPT_EVERY_MS = 3000

export function ConsolePage() {
  const { user } = useAuth()
  const [calls, setCalls] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState('')
  const [draftFrom, setDraftFrom] = useState('own')
  const [sending, setSending] = useState(false)
  const [warnings, setWarnings] = useState(null)
  const [faq, setFaq] = useState(null)
  const bottom = useRef(null)

  const refreshQueue = useCallback(async () => {
    try {
      const list = await api.calls(false)
      setCalls(list)
      setSelectedId((current) => current ?? list[0]?.id ?? null)
    } catch (err) {
      setError(err.message || 'Could not load the queue.')
    }
  }, [])

  const refreshDetail = useCallback(async (id) => {
    if (id == null) return
    try {
      setDetail(await api.call(id))
    } catch (err) {
      setError(err.message || 'Could not load this conversation.')
    }
  }, [])

  useEffect(() => {
    refreshQueue()
    const timer = setInterval(refreshQueue, QUEUE_EVERY_MS)
    return () => clearInterval(timer)
  }, [refreshQueue])

  useEffect(() => {
    setDetail(null)
    setDraft('')
    setDraftFrom('own')
    setWarnings(null)
    setFaq(null)
    refreshDetail(selectedId)
    const timer = setInterval(() => refreshDetail(selectedId), TRANSCRIPT_EVERY_MS)
    return () => clearInterval(timer)
  }, [selectedId, refreshDetail])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [detail?.turns?.length])

  async function accept(id) {
    setError('')
    try {
      await api.acceptHandoff(id)
      await refreshQueue()
      if (id === selectedId) await refreshDetail(id)
      else setSelectedId(id)
    } catch (err) {
      setError(err.message || 'Could not accept the handoff.')
      refreshQueue()
    }
  }

  async function send(content, action, force = false) {
    if (!content.trim() || sending) return
    setSending(true)
    setError('')
    try {
      const question = [...(detail?.turns ?? [])].reverse().find((t) => t.speaker === 'customer')?.content
      const result = await api.reply(detail.id, content.trim(), action, force)
      if (!result.sent) {
        setWarnings({ content, action, reasons: result.warnings })
        return
      }
      setWarnings(null)
      setDraft('')
      setDraftFrom('own')
      if (question) setFaq({ question, answer: content.trim(), saved: false })
      await refreshDetail(detail.id)
    } catch (err) {
      setError(err.message || 'Could not send the reply.')
    } finally {
      setSending(false)
    }
  }

  async function saveFaq() {
    try {
      const saved = await api.saveFaq(detail.id, faq.question, faq.answer)
      setFaq({ ...faq, saved: saved.chunk_id })
    } catch (err) {
      setError(err.message || 'Could not save the answer.')
    }
  }

  const turns = detail?.turns ?? []
  const spoken = turns.filter((t) => t.speaker !== 'system')
  const lastTurn = spoken[spoken.length - 1]
  const agentTurns = spoken.filter((t) => t.speaker === 'agent' && !t.meta?.bridging)
  const live = Boolean(detail && !detail.ended_at)
  const mine = detail?.handoff_status === 'accepted' && detail?.accepted_by === user.id
  const copilotHere = live && mine
  const awaitingReply = copilotHere && lastTurn?.speaker === 'customer'
  const suggestion = awaitingReply ? detail.suggestion : null

  const modeLine = !detail
    ? ''
    : detail.ended_at
      ? 'Ended'
      : detail.handoff_status === 'pending'
        ? 'Handoff waiting for a consultant'
        : detail.handoff_status === 'accepted'
          ? mine ? 'You are the consultant on this conversation' : 'Another consultant has this conversation'
          : 'The assistant is handling this conversation. You are observing.'

  return (
    <div className="flex h-full bg-surface">
      {/* Queue */}
      <aside className="flex w-[240px] flex-shrink-0 flex-col border-r border-line xl:w-[264px]">
        <div className="flex h-14 flex-shrink-0 items-center border-b border-line px-4 text-[13px] font-medium text-ink">Conversations</div>
        <nav className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
          {calls.length === 0 && <p className="px-3 py-2 text-[12.5px] text-faint">No conversations yet.</p>}
          {calls.map((call) => {
            const open = call.ended_at == null
            const selected = call.id === selectedId
            const waiting = call.handoff_status === 'pending'
            return (
              <div key={call.id} className="relative mb-0.5">
                <button
                  type="button"
                  onClick={() => setSelectedId(call.id)}
                  className={`flex w-full items-start gap-2.5 rounded-md py-2 pl-3 pr-2 text-left transition-colors hover:bg-hover ${selected ? 'font-medium' : ''}`}
                >
                  {selected && <span className="absolute left-0 top-2 h-[calc(100%-16px)] w-0.5 rounded-full bg-accent" />}
                  <span className={`mt-1.5 h-2 w-2 flex-shrink-0 rounded-full ${open ? 'bg-accent' : 'bg-line-2'}`} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center justify-between gap-2 text-[13px] text-ink">
                      <span className="truncate">{caller(call)}</span>
                      <span className="text-[11.5px] font-normal text-faint">{CHANNEL[call.channel] || call.channel}</span>
                    </span>
                    <span className="block text-[12px] font-normal text-muted">
                      {waiting ? 'Asked for a person' : call.handoff_status === 'accepted' ? 'With a consultant' : `${call.tier.toLowerCase()}, ${call.turn_count} ${call.turn_count === 1 ? 'turn' : 'turns'}`}
                    </span>
                    <span className="block text-[11.5px] font-normal text-faint">{when(call.started_at)}</span>
                  </span>
                </button>
                {waiting && open && (
                  <div className="px-3 pb-2 pl-[38px]">
                    <Button variant="primary" size="sm" onClick={() => accept(call.id)}>Accept</Button>
                  </div>
                )}
              </div>
            )
          })}
        </nav>
      </aside>

      {/* Transcript */}
      <main className="flex min-w-0 flex-1 flex-col">
        {detail ? (
          <>
            <header className="flex h-14 flex-shrink-0 items-center justify-between border-b border-line px-6">
              <div className="min-w-0">
                <div className="truncate text-[14px] font-medium leading-tight text-ink">
                  {caller(detail)}, {CHANNEL[detail.channel] || detail.channel}
                </div>
                <div className="truncate text-[12px] text-muted">{modeLine}</div>
              </div>
              <Tag tone={detail.ended_at ? 'outline' : 'accent'}>{detail.ended_at ? 'Ended' : detail.mode === 'copilot' ? 'Copilot' : 'Assistant'}</Tag>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-[720px] space-y-6 px-6 py-8">
                {spoken.length === 0 && <p className="text-center text-[12.5px] text-faint">Nothing said yet.</p>}
                {turns.map((turn) => (
                  <MessageBubble key={turn.id} turn={turn} perspective="staff" showMeta />
                ))}
                <div ref={bottom} />
              </div>
            </div>

            {live && detail.handoff_status === 'pending' && (
              <div className="flex flex-shrink-0 items-center justify-between border-t border-line px-6 py-3">
                <div className="text-[13px] text-muted">{detail.handoff_reason}</div>
                <Button variant="primary" size="sm" onClick={() => accept(detail.id)}>Accept this conversation</Button>
              </div>
            )}

            {copilotHere && (
              <div className="flex-shrink-0 border-t border-line px-6 py-4">
                {warnings && (
                  <div className="mb-3 space-y-2">
                    <Notice tone="danger">
                      The guard flagged this reply: {warnings.reasons.join(' ')}
                    </Notice>
                    <div className="flex gap-2">
                      <Button size="sm" onClick={() => { setDraft(warnings.content); setDraftFrom('edited'); setWarnings(null) }}>Fix it</Button>
                      <Button variant="danger" size="sm" disabled={sending} onClick={() => send(warnings.content, warnings.action, true)}>Send anyway</Button>
                    </div>
                  </div>
                )}
                {faq && !awaitingReply && (
                  <div className="mb-3 rounded-md border border-line p-3">
                    {faq.saved ? (
                      <p className="text-[12.5px] text-muted">Saved as FAQ entry {faq.saved}. The assistant can answer this itself from now on; QA sees it under Improvement.</p>
                    ) : (
                      <>
                        <div className="mb-1 text-[12px] text-muted">Save this answer so the assistant can give it next time?</div>
                        <p className="text-[12.5px] text-muted">Question: {faq.question}</p>
                        <textarea
                          value={faq.answer}
                          onChange={(e) => setFaq({ ...faq, answer: e.target.value })}
                          rows={2}
                          className="mt-2 w-full rounded-md border border-line px-3 py-2 text-[13px] text-ink outline-none focus:border-accent"
                        />
                        <p className="mt-1 text-[11.5px] text-faint">Remove anything that belongs only to this customer before saving.</p>
                        <div className="mt-2 flex gap-2">
                          <Button variant="primary" size="sm" onClick={saveFaq}>Save as FAQ</Button>
                          <Button size="sm" onClick={() => setFaq(null)}>Not now</Button>
                        </div>
                      </>
                    )}
                  </div>
                )}
                {suggestion && draftFrom === 'own' && !draft && (
                  <div className="mb-3 rounded-md border border-line p-3">
                    <div className="mb-1 text-[12px] text-muted">Suggested by the assistant</div>
                    <p className="text-[13.5px] leading-[1.6] text-ink">{suggestion.text}</p>
                    {suggestion.used_lines?.length > 0 && (
                      <div className="mt-1.5 text-[12px] text-muted">Cites {suggestion.used_lines.join(', ')}</div>
                    )}
                    {suggestion.warnings?.length > 0 && (
                      <div className="mt-2"><Notice tone="danger">{suggestion.warnings.join(' ')}</Notice></div>
                    )}
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button variant="primary" size="sm" disabled={sending} onClick={() => send(suggestion.text, 'used')}>Send as written</Button>
                      <Button size="sm" onClick={() => { setDraft(suggestion.text); setDraftFrom('edited') }}>Edit first</Button>
                    </div>
                  </div>
                )}
                <div className="flex items-end gap-2">
                  <textarea
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        send(draft, draftFrom === 'edited' ? 'edited' : 'own')
                      }
                    }}
                    rows={2}
                    placeholder={awaitingReply ? 'Reply to the customer' : 'Say something to the customer'}
                    className="min-h-[44px] flex-1 rounded-md border border-line px-3 py-2 text-[13.5px] text-ink placeholder:text-faint outline-none focus:border-accent focus:shadow-input"
                  />
                  <Button variant="primary" disabled={sending || !draft.trim()} onClick={() => send(draft, draftFrom === 'edited' ? 'edited' : 'own')}>
                    Send
                  </Button>
                </div>
                {draftFrom === 'edited' && (
                  <div className="mt-1.5 text-[12px] text-faint">Editing the suggestion; the difference is kept as feedback.</div>
                )}
              </div>
            )}
          </>
        ) : (
          <div className="flex flex-1 items-center justify-center text-[13px] text-faint">
            {selectedId == null ? 'Select a conversation.' : 'Loading'}
          </div>
        )}
        {error && (
          <p role="alert" className="mx-6 mb-3 border-l-2 border-danger pl-3 text-[13px] text-ink">
            {error}
          </p>
        )}
      </main>

      {/* Evidence */}
      <aside className="hidden w-[340px] flex-shrink-0 flex-col border-l border-line lg:flex xl:w-[380px]">
        <div className="flex h-14 flex-shrink-0 items-center border-b border-line px-5 text-[13px] font-medium text-ink">Evidence</div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {detail && (
            <>
              <Section title="Call brief">
                {detail.warnings.length > 0 && (
                  <div className="mb-3 space-y-2">
                    {detail.warnings.map((warning, index) => (
                      <Notice key={index}>{warning}</Notice>
                    ))}
                  </div>
                )}
                {detail.brief.length === 0 ? (
                  <p className="text-[12.5px] text-faint">
                    {detail.tier === 'UNKNOWN' ? 'Not identified, so nothing to carry over.'
                      : detail.tier === 'AMBIGUOUS' ? 'A shared number: nobody\'s brief loads until the caller says who they are.'
                      : 'Known, nothing to carry over.'}
                  </p>
                ) : (
                  <ol className="space-y-1.5">
                    {detail.brief.map((line) => {
                      const withheld = line.sensitive && detail.tier !== 'VERIFIED'
                      return (
                        <li key={line.id} className="flex gap-2 text-[12.5px] leading-snug">
                          <span className="w-6 flex-shrink-0 text-[11.5px] text-faint">{line.id}</span>
                          <span className={withheld ? 'text-faint' : 'text-ink'}>
                            {line.text}
                            {withheld && <span className="ml-1 text-[11px]">(withheld until verified)</span>}
                          </span>
                        </li>
                      )
                    })}
                  </ol>
                )}
                {detail.brief_object?.is_returning && (
                  <dl className="mt-3 grid grid-cols-[96px_1fr] gap-y-1 border-t border-line pt-3 text-[12.5px]">
                    <dt className="text-muted">Do not ask</dt>
                    <dd className="text-ink">{detail.brief_object.must_not_ask.join(', ') || 'nothing'}</dd>
                    <dt className="text-muted">Opening</dt>
                    <dd className="text-ink">{detail.brief_object.suggested_opening}</dd>
                    <dt className="text-muted">Ready in</dt>
                    <dd className="text-ink">{detail.brief_object.latency_ms} ms, price and stock re-checked for {detail.business_day}</dd>
                  </dl>
                )}
              </Section>

              <Section title="Context">
                <dl className="grid grid-cols-[88px_1fr] gap-y-1 text-[12.5px]">
                  <dt className="text-muted">Customer</dt>
                  <dd className="text-ink">{detail.customer_id ? `${detail.customer_label || ''} (${detail.customer_id})`.trim() : 'not known'}</dd>
                  <dt className="text-muted">Tier</dt>
                  <dd className="text-ink">{detail.tier}</dd>
                  <dt className="text-muted">Lane</dt>
                  <dd className="text-ink">{detail.lane}{detail.route_reason ? `, ${detail.route_reason}` : ''}</dd>
                  <dt className="text-muted">Mode</dt>
                  <dd className="text-ink">{detail.mode}</dd>
                  <dt className="text-muted">Day</dt>
                  <dd className="text-ink">{detail.business_day}</dd>
                  {detail.handoff_status && (
                    <>
                      <dt className="text-muted">Handoff</dt>
                      <dd className="text-ink">{detail.handoff_status}{detail.handoff_reason ? `, ${detail.handoff_reason}` : ''}</dd>
                    </>
                  )}
                </dl>
              </Section>

              {detail.handoff_brief && (
                <Section title="Handoff brief">
                  <HandoffBrief brief={detail.handoff_brief} />
                </Section>
              )}

              <Section title="Assistant turns">
                {agentTurns.length === 0 && <p className="text-[12.5px] text-faint">No assistant turn yet.</p>}
                <div className="space-y-3">
                  {agentTurns.map((turn, index) => (
                    <AgentTurn key={turn.id} turn={turn} index={index} />
                  ))}
                </div>
              </Section>

              {detail.ended_at && (
                <Section title="After the call">
                  <AfterCall status={detail.memory_status} result={detail.after_call} />
                </Section>
              )}
            </>
          )}
        </div>
      </aside>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <section className="border-b border-line px-5 py-4">
      <h2 className="mb-2.5 text-[13px] font-medium text-ink">{title}</h2>
      {children}
    </section>
  )
}

function when(iso) {
  const date = new Date(iso)
  return date.toLocaleString(undefined, { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' })
}

const CHANNEL = { web: 'website chat', zalo: 'Zalo', hotline: 'hotline', facebook: 'Facebook' }

function caller(call) {
  if (call.customer_label) return call.customer_label
  if (call.phone_last4) return `Number ending ${call.phone_last4}`
  if (call.channel_ref) return call.channel_ref
  return 'Anonymous'
}

function seconds(ms) {
  return ms == null ? null : `${(ms / 1000).toFixed(1)} s`
}

function AgentTurn({ turn, index }) {
  const meta = turn.meta || {}
  const latency = meta.latency || {}
  const guard = meta.guard || {}
  const soft = guard.soft
  const timings = [
    latency.ttft_ms != null && `answer ${seconds(latency.ttft_ms)}`,
    latency.ttfa_ms != null && `first audio ${seconds(latency.ttfa_ms)}`,
    meta.call_brief_latency_ms != null && `brief ${meta.call_brief_latency_ms} ms`,
  ].filter(Boolean)
  return (
    <div className="rounded-md border border-line p-2.5">
      <div className="mb-1 flex items-center justify-between gap-2 text-[12px] text-muted">
        <span>Turn {index + 1}{meta.lane ? `, ${meta.lane}` : ''}</span>
        <span>{timings.join(', ')}</span>
      </div>
      {meta.bridging && <p className="text-[12px] text-muted">The bridging line, said once by the harness.</p>}
      {meta.used_brief_lines?.length > 0 && <p className="text-[12px] text-muted">Cited {meta.used_brief_lines.join(', ')}</p>}
      {meta.tool_calls?.length ? (
        <ul className="mt-1.5 space-y-1.5">
          {meta.tool_calls.map((call, i) => (
            <li key={i} className="rounded border border-line px-2 py-1.5 font-mono text-[11px] leading-snug text-ink">
              <div className="font-semibold">
                {call.name}
                {call.result && !call.result.ok && <span className="ml-1 font-normal text-danger">{call.result.error?.code}</span>}
                {call.blocked_by && <span className="ml-1 font-normal text-danger">stopped before it ran</span>}
              </div>
              <div className="text-muted">{JSON.stringify(call.args)}</div>
              {call.result && (
                <div className="mt-1 max-h-24 overflow-y-auto whitespace-pre-wrap break-all text-faint">
                  {JSON.stringify(call.result.ok ? call.result.data : call.result.error)}
                </div>
              )}
            </li>
          ))}
        </ul>
      ) : (
        !meta.bridging && <p className="text-[12px] text-faint">No tool called.</p>
      )}
      {(guard.hard || soft) && (
        <p className="mt-1.5 text-[12px] text-muted">
          Guard: {guard.fallback ? 'blocked, the safe line was said' : guard.passed ? 'passed' : 'flagged'}
          {soft && (soft.decided_by === 'jev' ? `, policy checked by Jev in ${soft.seconds} s` : `, policy check ${soft.decided_by}`)}
          {meta.regenerations > 0 && `, ${meta.regenerations} regenerated`}
        </p>
      )}
      {meta.blocked_drafts?.length > 0 && (
        <ul className="mt-1.5 space-y-1.5">
          {meta.blocked_drafts.map((blocked, i) => (
            <li key={i} className="border-l-2 border-danger pl-2 text-[12px] leading-snug">
              <span className="text-faint line-through">{blocked.text || '(empty)'}</span>
              <span className="block text-ink">{blocked.reasons.join(' ')}</span>
            </li>
          ))}
        </ul>
      )}
      {meta.error && <p className="mt-1.5 text-[12px] text-danger">{meta.error}</p>}
    </div>
  )
}

function HandoffBrief({ brief }) {
  const rows = [
    ['Reason', [brief.escalation_reason, brief.escalation_reason_detail].filter(Boolean).join(': ')],
    ['Summary', brief.conversation_summary],
    ['Advised', [brief.product_advised, brief.price_quoted_vnd && `${brief.price_quoted_vnd.toLocaleString('vi-VN')}đ`].filter(Boolean).join(', ')],
    ['Unanswered', (brief.open_questions || []).join('; ')],
    ['Do next', brief.next_action],
  ].filter(([, v]) => v)
  return (
    <dl className="grid grid-cols-[88px_1fr] gap-y-1.5 text-[12.5px]">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

function AfterCall({ status, result }) {
  if (!status || status === 'pending') return <p className="text-[12.5px] text-faint">Remembering this call.</p>
  if (status !== 'done') {
    return <p className="text-[12.5px] text-muted">{status === 'skipped' ? `Nothing written: ${result?.reason}.` : `Failed: ${result?.error || result?.reason}. It runs again at the next start.`}</p>
  }
  return (
    <div className="space-y-2 text-[12.5px]">
      {result?.episode && <p className="text-ink">{result.episode}</p>}
      <ul className="space-y-1">
        {(result?.memory_writes || []).map((w, i) => (
          <li key={i} className="flex gap-2">
            <span className="w-16 flex-shrink-0 text-faint">{w.op}</span>
            <span className="text-ink">{w.key} = {JSON.stringify(w.value)}</span>
          </li>
        ))}
      </ul>
      <p className="text-[12px] text-muted">Written to {result?.customer_id} by the MemoryAgent. Tagged {result?.tags?.situation}, {result?.tags?.outcome}.</p>
    </div>
  )
}
