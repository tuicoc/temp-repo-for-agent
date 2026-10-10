// The chat screen: a list of conversations, the current one, and the composer.
//
// A turn is sent over SSE. The backend answers with a filler frame straight
// away, then the finished reply — not a token stream, because docs/flow.md
// section 8.4 requires the guardrail to see a complete sentence before the
// customer does. The typing indicator below is therefore honest: something is
// happening, and nothing is being shown that has not been checked.

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, sendMessage } from '../services/api'
import { useAuth } from '../context/AuthContext'
import { ChatInput } from '../components/ChatInput'
import { MessageBubble } from '../components/MessageBubble'
import { Sidebar } from '../components/Sidebar'

export function ChatPage() {
  const { user, logout } = useAuth()
  const [conversations, setConversations] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])
  const [models, setModels] = useState([])
  const [model, setModel] = useState(null)
  const [pending, setPending] = useState(null)
  const [error, setError] = useState('')
  const [sandboxOpen, setSandboxOpen] = useState(false)
  const [sandboxPhone, setSandboxPhone] = useState('')
  const [sandboxChannel, setSandboxChannel] = useState('web')
  const [sandboxCall, setSandboxCall] = useState(null)
  const [sandboxTimeline, setSandboxTimeline] = useState([])
  const [callBrief, setCallBrief] = useState(null)
  const [callStatusMessage, setCallStatusMessage] = useState('')
  const [sharedModel, setSharedModel] = useState(null)
  const [lastCompletedCallId, setLastCompletedCallId] = useState(null)
  const [gapQuestion, setGapQuestion] = useState('')
  const [gapIntent, setGapIntent] = useState('')
  const [gapSignalKind, setGapSignalKind] = useState('qa_feedback')
  const [gapNote, setGapNote] = useState('')
  const [gapCandidates, setGapCandidates] = useState([])
  const [approvedGaps, setApprovedGaps] = useState([])
  const [selectedGapId, setSelectedGapId] = useState('')
  const [gapEdits, setGapEdits] = useState({})
  const [callStatuses, setCallStatuses] = useState([])
  const [reconcileReason, setReconcileReason] = useState('')
  const [r0CallId, setR0CallId] = useState('')
  const [r1CallId, setR1CallId] = useState('')
  const [comparisonReport, setComparisonReport] = useState(null)
  const [pairTurns, setPairTurns] = useState('')
  const [pairBudget, setPairBudget] = useState(3)
  const bottom = useRef(null)

  useEffect(() => {
    api.models().then((list) => {
      setModels(list)
      setModel(list[0] ?? null)
    }).catch(() => setError('Could not load the model list.'))
    refreshConversations()
    api.evaluationCapabilities().then(setSharedModel).catch(() => setSharedModel(null))
  }, [])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, pending])

  const refreshConversations = useCallback(async () => {
    try {
      const list = await api.conversations()
      setConversations(list)
      setActiveId((current) => current ?? list[0]?.id ?? null)
    } catch {
      setError('Could not load your conversations.')
    }
  }, [])

  useEffect(() => {
    if (activeId == null) {
      setMessages([])
      return
    }
    api.messages(activeId).then(setMessages).catch(() => setError('Could not load this conversation.'))
  }, [activeId])

  useEffect(() => {
    if (!sandboxOpen) return
    api.evaluationGaps().then(setGapCandidates).catch(() => setGapCandidates([]))
    api.approvedEvaluationGaps().then(setApprovedGaps).catch(() => setApprovedGaps([]))
    api.evaluationCallStatuses().then(setCallStatuses).catch(() => setCallStatuses([]))
  }, [sandboxOpen])

  async function handleCreate() {
    const conversation = await api.createConversation()
    setConversations((list) => [conversation, ...list])
    setActiveId(conversation.id)
    setMessages([])
  }

  async function handleDelete(id) {
    await api.deleteConversation(id)
    setConversations((list) => list.filter((c) => c.id !== id))
    if (id === activeId) setActiveId(null)
  }

  async function endSharedCall() {
    if (!activeId) return
    try {
      const result = await api.endConversationCall(activeId)
      setCallStatusMessage(result.status === 'COMPLETED' ? 'Call completed — memory saved.' : 'No open call.')
    } catch (err) { setError(err.message || 'Call needs reconciliation.') }
  }

  async function handleSend(content) {
    setError('')
    setPending({ filler: '' })

    try {
      if (sandboxCall) {
        const result = await api.evaluationTurn(sandboxCall.call_id, content)
        setSandboxTimeline(result.timeline ?? [])
        setCallBrief(result.call_brief ?? callBrief)
        setMessages((result.timeline ?? []).map((message, index) => ({ id: `sandbox-${message.turn}-${index}`, ...message })))
        return
      }
      let conversationId = activeId

      // Typing before picking a conversation should just work.
      if (conversationId == null) {
        const conversation = await api.createConversation()
        setConversations((list) => [conversation, ...list])
        setActiveId(conversation.id)
        conversationId = conversation.id
      }

      setMessages((list) => [...list, { id: `local-${Date.now()}`, role: 'user', content }])
      await sendMessage(
        conversationId,
        { content, provider: model?.provider, model: model?.id },
        {
          filler: (data) => setPending({ filler: data.text }),
          message: (data) =>
            setMessages((list) => [
              ...list,
              {
                id: `reply-${Date.now()}`,
                role: 'assistant',
                content: data.content,
                model: data.model,
                confidence: data.confidence,
              },
            ]),
          error: (data) => setError(data.message),
        },
      )
      refreshConversations()
    } catch (err) {
      setError(err.message || 'The agent could not be reached.')
    } finally {
      setPending(null)
    }
  }

  async function startSandboxCall() {
    setError('')
    try {
      const call = await api.evaluationCallStart({ customer_phone: sandboxPhone, channel: sandboxChannel, candidate_id: selectedGapId || null })
      setSandboxCall(call)
      setLastCompletedCallId(null)
      setCallBrief(call.call_brief)
      setSandboxTimeline([])
      setMessages([])
      setCallStatusMessage('')
      setCallStatuses(await api.evaluationCallStatuses())
    } catch (err) {
      setError(err.message || 'Could not start the local evaluation call.')
    }
  }

  async function endSandboxCall() {
    if (!sandboxCall) return
    try {
      const result = await api.evaluationCallEnd(sandboxCall.call_id)
      setLastCompletedCallId(sandboxCall.call_id)
      setSandboxCall(null)
      setCallBrief(null)
      setSandboxTimeline([])
      setCallStatusMessage(`Call completed — memory saved; outcome signals: ${result.outcome_signals?.status ?? 'pending'}.`)
      setCallStatuses(await api.evaluationCallStatuses())
      setGapCandidates(await api.evaluationGaps())
    } catch (err) {
      setError(err.message || 'The call did not pass its save barrier; it remains open for reconciliation.')
    }
  }

  async function submitGapSignal() {
    if (!lastCompletedCallId) return
    try {
      await api.submitEvaluationGap({ call_id: lastCompletedCallId, question: gapQuestion, intent: gapIntent,
        signal_kind: gapSignalKind, note: gapNote })
      setGapQuestion('')
      setGapNote('')
      setCallStatusMessage('QA signal saved in the local knowledge-gap queue.')
      setGapCandidates(await api.evaluationGaps())
    } catch (err) { setError(err.message || 'Could not record the QA signal.') }
  }

  async function saveGapEdit(candidate) {
    const edit = gapEdits[candidate.candidate_id] ?? {}
    try {
      await api.editEvaluationGap(candidate.candidate_id, { answer: edit.answer ?? candidate.answer,
        source_path: edit.source_path ?? candidate.source_path ?? 'policy/faq.md',
        source_excerpt: edit.source_excerpt ?? candidate.source_excerpt ?? '' })
      setGapCandidates(await api.evaluationGaps())
    } catch (err) { setError(err.message || 'Could not save the candidate revision.') }
  }

  async function decideGap(candidate, approve) {
    try {
      if (approve) await api.approveEvaluationGap(candidate.candidate_id, 'QA verified against the pinned policy source.')
      else await api.rejectEvaluationGap(candidate.candidate_id, 'QA rejected this candidate.')
      setGapCandidates(await api.evaluationGaps())
      setApprovedGaps(await api.approvedEvaluationGaps())
    } catch (err) { setError(err.message || 'Could not record the QA decision.') }
  }

  async function reconcileInterruptedCall(callId) {
    try {
      const result = await api.reconcileEvaluationCall(callId, reconcileReason)
      setCallStatusMessage(`Interrupted call reconciled by QA; outcome signals: ${result.outcome_signals?.status ?? 'pending'}.`)
      setCallStatuses(await api.evaluationCallStatuses())
      setGapCandidates(await api.evaluationGaps())
      setReconcileReason('')
    } catch (err) { setError(err.message || 'Cannot reconcile this call; inspect tool and memory evidence.') }
  }

  async function retryOutcomeProducer(callId) {
    try {
      const result = await api.produceEvaluationGaps(callId)
      setCallStatusMessage(`${result.signal_count} grounded outcome signals recorded.`)
      setGapCandidates(await api.evaluationGaps())
    } catch (err) { setError(err.message || 'Outcome producer failed.') }
  }

  async function compareRounds() {
    try {
      const result = await api.compareEvaluationRounds(r0CallId, r1CallId)
      setComparisonReport(result)
    } catch (err) { setError(err.message || 'Could not compare the two sandbox runs.') }
  }

  async function runPair() {
    const turns = pairTurns.split('\n').map((line) => line.trim()).filter(Boolean)
    if (!selectedGapId || !turns.length) return
    try {
      const report = await api.runEvaluationPair({ candidate_id: selectedGapId, turns, model_call_budget: Number(pairBudget) })
      setComparisonReport(report)
      setCallStatuses(await api.evaluationCallStatuses())
      setCallStatusMessage(`Paired run saved: ${report.decision}. Quality still requires evaluator scoring.`)
    } catch (err) { setError(err.message || 'Paired run stopped; inspect the persisted call status.') }
  }

  return (
    <div className="flex h-full">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={setActiveId}
        onCreate={handleCreate}
        onDelete={handleDelete}
        email={user.email}
        onLogout={logout}
      />

      <main className="flex min-w-0 flex-1 flex-col bg-surface">
        <section className="border-b border-line bg-white px-4 py-3">
          <div className="mx-auto flex w-full max-w-[720px] items-center justify-between">
            <div>
              <h2 className="text-[13px] font-semibold text-ink">Evaluation sandbox</h2>
              <p className="text-[11px] text-muted">Local PostgreSQL + BTC mock tools; feature flag required. Do not enter real customer data.</p>
            </div>
            <button className="rounded-md border px-3 py-1.5 text-[12px]" onClick={() => setSandboxOpen((open) => !open)}>
              {sandboxOpen ? 'Hide' : 'Open'}
            </button>
          </div>
          {sharedModel && activeId && !sandboxCall && (
            <div className="mx-auto mt-2 flex w-full max-w-[720px] items-center justify-between text-[11px] text-muted">
              <span>Chat này dùng shared runtime · model {sharedModel.model} · identity ẩn danh theo conversation.</span>
              <button className="rounded-md border px-2 py-1 text-[12px]" disabled={Boolean(pending)} onClick={endSharedCall}>End chat call</button>
            </div>
          )}
          {sandboxOpen && (
            <div className="mx-auto mt-3 w-full max-w-[720px] space-y-3">
              {!sandboxCall ? (
                <div className="flex flex-wrap items-end gap-2">
                  <label className="flex min-w-[180px] flex-1 flex-col gap-1 text-[11px] text-muted">
                    Synthetic customer phone
                    <input className="rounded-md border px-2 py-1.5 text-[13px] text-ink" value={sandboxPhone} onChange={(event) => setSandboxPhone(event.target.value)} placeholder="e.g. 0984726714" />
                  </label>
                  <label className="flex flex-col gap-1 text-[11px] text-muted">
                    Channel
                    <select className="rounded-md border bg-white px-2 py-1.5 text-[13px] text-ink" value={sandboxChannel} onChange={(event) => setSandboxChannel(event.target.value)}>
                      <option value="web">Web</option><option value="phone">Phone</option><option value="zalo">Zalo</option><option value="facebook">Facebook</option>
                    </select>
                  </label>
                  {approvedGaps.length > 0 && (
                    <label className="flex min-w-[180px] flex-col gap-1 text-[11px] text-muted">
                      Optional QA-approved FAQ sandbox candidate
                      <select className="rounded-md border bg-white px-2 py-1.5 text-[13px] text-ink" value={selectedGapId} onChange={(event) => setSelectedGapId(event.target.value)}>
                        <option value="">None</option>{approvedGaps.map((item) => <option key={item.candidate_id} value={item.candidate_id}>{item.candidate_id} · {item.question.slice(0, 40)}</option>)}
                      </select>
                    </label>
                  )}
                  <button className="rounded-md bg-ink px-3 py-1.5 text-[12px] text-white disabled:opacity-50" disabled={!sandboxPhone.trim() || Boolean(pending)} onClick={startSandboxCall}>Start sandbox call</button>
                </div>
              ) : (
                <div className="flex items-center justify-between rounded-md bg-surface px-3 py-2 text-[12px]">
                  <span>Call {sandboxCall.call_id} · {sandboxCall.status} · max {sandboxCall.model_call_budget} model calls</span>
                  <button className="rounded-md border px-3 py-1 text-[12px]" disabled={Boolean(pending)} onClick={endSandboxCall}>End call / save</button>
                </div>
              )}
              {callStatusMessage && <p role="status" className="text-[12px] text-emerald-700">{callStatusMessage}</p>}
              {callBrief && (
                <div className="rounded-md border p-3 text-[12px]">
                  <p className="font-medium">Call Brief · {callBrief.identity_status} · {callBrief.is_returning ? 'returning' : 'new'}</p>
                  {Object.entries(callBrief.profile_facts ?? {}).map(([key, value]) => <p key={key} className="mt-1 text-muted">{key}: {String(value)}</p>)}
                  {callBrief.last_session?.summary && <p className="mt-2 text-muted">Previous call: {callBrief.last_session.summary}</p>}
                  {callBrief.products_advised?.length > 0 && <p className="mt-1 text-muted">Previously discussed: {callBrief.products_advised.map((item) => item.name || item.sku || item).join(', ')}</p>}
                  {callBrief.stale_warnings?.map((warning) => <p key={warning} className="mt-1 text-amber-700">{warning}</p>)}
                </div>
              )}
              {lastCompletedCallId && (
                <div className="space-y-2 rounded-md border p-3">
                  <p className="text-[12px] font-medium">Record a grounded QA signal</p>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <input className="rounded-md border px-2 py-1.5 text-[12px]" value={gapQuestion} onChange={(event) => setGapQuestion(event.target.value)} placeholder="Exact customer question from this call" />
                    <input className="rounded-md border px-2 py-1.5 text-[12px]" value={gapIntent} onChange={(event) => setGapIntent(event.target.value)} placeholder="Intent, e.g. pricing" />
                    <select className="rounded-md border bg-white px-2 py-1.5 text-[12px]" value={gapSignalKind} onChange={(event) => setGapSignalKind(event.target.value)}>
                      <option value="qa_feedback">QA feedback</option><option value="customer_repeat">Customer repeated</option><option value="out_of_scope">Out of scope</option><option value="outcome">Grounded outcome</option>
                    </select>
                    <input className="rounded-md border px-2 py-1.5 text-[12px]" value={gapNote} onChange={(event) => setGapNote(event.target.value)} placeholder="Evidence note (no personal data)" />
                  </div>
                  <button className="rounded-md border px-3 py-1 text-[12px] disabled:opacity-50" disabled={!gapQuestion.trim() || !gapIntent.trim()} onClick={submitGapSignal}>Queue gap</button>
                </div>
              )}
              {gapCandidates.length > 0 && (
                <div className="space-y-3 rounded-md border p-3">
                  <p className="text-[12px] font-medium">QA review · candidates stay inactive until explicitly selected for sandbox</p>
                  {gapCandidates.map((candidate) => {
                    const edit = gapEdits[candidate.candidate_id] ?? {}
                    const update = (key, value) => setGapEdits((current) => ({ ...current, [candidate.candidate_id]: { ...current[candidate.candidate_id], [key]: value } }))
                    return <div key={candidate.candidate_id} className="space-y-2 border-t pt-2 text-[12px]">
                      <p>{candidate.candidate_id} · {candidate.status} · {candidate.signals?.length ?? 0} signals</p>
                      <p className="text-muted">{candidate.question} · {candidate.intent}</p>
                      <textarea className="w-full rounded-md border p-2" value={edit.answer ?? candidate.answer ?? ''} onChange={(event) => update('answer', event.target.value)} placeholder="Answer grounded in a pinned public policy source" />
                      <select className="rounded-md border bg-white px-2 py-1" value={edit.source_path ?? candidate.source_path ?? 'policy/faq.md'} onChange={(event) => update('source_path', event.target.value)}>
                        {['policy/faq.md','policy/chinh-sach-doi-tra.md','policy/chinh-sach-bao-hanh.md','policy/chinh-sach-van-chuyen-thanh-toan.md','policy/dieu-khoan-khuyen-mai.md','policy/spec-gia-dung.md','policy/playbook-telesale.md'].map((path) => <option key={path} value={path}>{path}</option>)}
                      </select>
                      <textarea className="w-full rounded-md border p-2" value={edit.source_excerpt ?? candidate.source_excerpt ?? ''} onChange={(event) => update('source_excerpt', event.target.value)} placeholder="Paste an exact excerpt from the selected source" />
                      <div className="flex flex-wrap gap-2">
                        <button className="rounded-md border px-2 py-1" onClick={() => saveGapEdit(candidate)}>Save revision</button>
                        <button className="rounded-md border px-2 py-1" disabled={!candidate.answer || !candidate.source_hash} onClick={() => decideGap(candidate, true)}>Approve (sign)</button>
                        <button className="rounded-md border px-2 py-1" onClick={() => decideGap(candidate, false)}>Reject</button>
                      </div>
                    </div>
                  })}
                </div>
              )}
              {callStatuses.length > 0 && (
                <div className="space-y-2 rounded-md border p-3 text-[12px]">
                  <p className="font-medium">Persisted call status</p>
                  {callStatuses.map((item) => <div key={item.call_id} className="border-t pt-2">
                    <span>{item.call_id} · {item.call} · {item.status}</span>
                    {item.status === 'RECONCILIATION_REQUIRED' && <div className="mt-2 flex flex-wrap gap-2">
                      <input className="min-w-[220px] flex-1 rounded-md border px-2 py-1" value={reconcileReason} onChange={(event) => setReconcileReason(event.target.value)} placeholder="QA reason after checking persisted turns/tools" />
                      <button className="rounded-md border px-2 py-1" disabled={reconcileReason.trim().length < 5} onClick={() => reconcileInterruptedCall(item.call_id)}>Reconcile</button>
                    </div>}
                    {item.status === 'COMPLETED' && <div className="mt-2 flex gap-2">
                      <button className="rounded-md border px-2 py-1" onClick={() => setLastCompletedCallId(item.call_id)}>Use for QA signal</button>
                      <button className="rounded-md border px-2 py-1" onClick={() => retryOutcomeProducer(item.call_id)}>Retry outcome signals</button>
                    </div>}
                  </div>)}
                </div>
              )}
              {callStatuses.filter((item) => item.status === 'COMPLETED').length >= 2 && (
                <div className="space-y-2 rounded-md border p-3 text-[12px]">
                  <p className="font-medium">R0→R1 sandbox comparison</p>
                  <div className="flex flex-wrap gap-2">
                    <select className="rounded-md border bg-white px-2 py-1" value={r0CallId} onChange={(event) => setR0CallId(event.target.value)}><option value="">R0 · candidate off</option>{callStatuses.filter((item) => item.status === 'COMPLETED').map((item) => <option key={item.call_id} value={item.call_id}>{item.call_id}</option>)}</select>
                    <select className="rounded-md border bg-white px-2 py-1" value={r1CallId} onChange={(event) => setR1CallId(event.target.value)}><option value="">R1 · approved candidate</option>{callStatuses.filter((item) => item.status === 'COMPLETED').map((item) => <option key={item.call_id} value={item.call_id}>{item.call_id}</option>)}</select>
                    <button className="rounded-md border px-2 py-1" disabled={!r0CallId || !r1CallId || r0CallId === r1CallId} onClick={compareRounds}>Compare controls</button>
                  </div>
                  {comparisonReport && <p role="status">{comparisonReport.decision} · controls {comparisonReport.controls_pass ? 'match' : 'mismatch'} · quality {comparisonReport.quality_status}</p>}
                </div>
              )}
              {approvedGaps.length > 0 && (
                <div className="space-y-2 rounded-md border p-3 text-[12px]">
                  <p className="font-medium">Run a controlled R0→R1 sandbox pair</p>
                  <p className="text-muted">Use the same synthetic customer turns in both rounds; only the approved FAQ changes. This calls the configured model.</p>
                  <textarea className="w-full rounded-md border p-2" value={pairTurns} onChange={(event) => setPairTurns(event.target.value)} placeholder="One synthetic customer turn per line" />
                  <div className="flex flex-wrap items-center gap-2">
                    <input className="w-16 rounded-md border px-2 py-1" type="number" min="1" max="12" value={pairBudget} onChange={(event) => setPairBudget(event.target.value)} aria-label="Model attempts per call" />
                    <span>attempts per call; up to {Number(pairBudget) * 2} across R0/R1</span>
                    <button className="rounded-md border px-2 py-1" disabled={!selectedGapId || !pairTurns.trim() || pairBudget < 1 || pairBudget > 12 || Boolean(pending)} onClick={runPair}>Run controlled pair</button>
                  </div>
                </div>
              )}
              {sandboxTimeline.length > 0 && <p className="text-[11px] text-muted">{sandboxTimeline.length} turns in the sandbox timeline</p>}
            </div>
          )}
        </section>
        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[720px] space-y-6 px-4 py-8">
            {messages.length === 0 && !pending && (
              <div className="pt-24 text-center">
                <h2 className="text-[22px] font-semibold tracking-[-0.01em] text-ink">How can we help?</h2>
                <p className="mt-2 text-[13.5px] text-muted">
                  Ask about a product and the assistant will answer in Vietnamese.
                </p>
              </div>
            )}

            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}

            {pending && (
              <div className="msg-enter flex justify-start gap-3">
                <div
                  className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full shadow-sm"
                  style={{ background: 'linear-gradient(135deg, #E07840 0%, #C04898 100%)' }}
                >
                  <span className="text-[10px] font-semibold text-white">A</span>
                </div>
                <div className="inline-flex items-center gap-2 pt-1 text-[14px] text-muted">
                  <span className="flex gap-1">
                    <Dot delay="0ms" />
                    <Dot delay="150ms" />
                    <Dot delay="300ms" />
                  </span>
                  {pending.filler}
                </div>
              </div>
            )}

            {error && (
              <p role="alert" className="rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-[12px] text-red-700">
                {error}
              </p>
            )}

            <div ref={bottom} />
          </div>
        </div>

        <ChatInput
          models={sharedModel ? [{ id: sharedModel.model, provider: sharedModel.provider, label: sharedModel.model }] : models}
          model={sharedModel?.model ?? model?.id}
          onModelChange={setModel}
          onSend={handleSend}
          busy={Boolean(pending)}
        />
      </main>
    </div>
  )
}

function Dot({ delay }) {
  return (
    <span
      className="h-1.5 w-1.5 animate-bounce rounded-full bg-faint"
      style={{ animationDelay: delay }}
    />
  )
}
