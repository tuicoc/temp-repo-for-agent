// QA review: the page that answers "why did the assistant say that", and
// where a person scores a sample against the same rubric the judge uses —
// the human-in-the-loop half of docs/flow.md section 17.5, which is what
// produces the agreement figure.
//
// Three panes that each scroll on their own, so nothing pushes the page
// down: the conversations, the transcript, and the evidence for the
// selected assistant turn under three tabs — what it had and did, the trace
// behind the model call, and the rubric. Sample data throughout.

import { useState } from 'react'
import { ExternalLink } from 'lucide-react'
import { Button, Kv, Notice, Tabs, Tag } from '../components/ui'
import { MessageBubble } from '../components/MessageBubble'
import { qaCalls } from '../mock/data'

const TABS = [
  { id: 'evidence', label: 'Evidence' },
  { id: 'trace', label: 'Trace' },
  { id: 'rubric', label: 'Rubric' },
]

export function QaPage() {
  const [callId, setCallId] = useState(qaCalls[0].id)
  const call = qaCalls.find((c) => c.id === callId)
  const agentTurns = call.turns.filter((t) => t.detail)
  const [turnId, setTurnId] = useState(agentTurns[0].id)
  const turn = call.turns.find((t) => t.id === turnId && t.detail) ?? agentTurns[0]
  const [tab, setTab] = useState('evidence')
  const [scores, setScores] = useState({})
  const [note, setNote] = useState('')
  const [verdict, setVerdict] = useState(null)

  function selectCall(id) {
    setCallId(id)
    setTurnId(qaCalls.find((c) => c.id === id).turns.find((t) => t.detail).id)
    setVerdict(null)
    setScores({})
  }

  const key = (item) => `${callId}-${turn.id}-${item.id}`
  const detail = turn.detail
  const turnNumber = agentTurns.findIndex((t) => t.id === turn.id) + 1

  return (
    <div className="flex h-full bg-surface">
      <aside className="flex w-[240px] flex-shrink-0 flex-col border-r border-line xl:w-[264px]">
        <div className="flex h-14 flex-shrink-0 items-center border-b border-line px-4 text-[13px] font-medium text-ink">
          Conversations <span className="ml-2 font-normal text-faint">sample</span>
        </div>
        <nav className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
          {qaCalls.map((c) => {
            const selected = c.id === callId
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => selectCall(c.id)}
                className={`relative mb-0.5 w-full rounded-md py-2 pl-3 pr-2 text-left transition-colors hover:bg-hover ${selected ? 'font-medium' : ''}`}
              >
                {selected && <span className="absolute left-0 top-2 h-[calc(100%-16px)] w-0.5 rounded-full bg-accent" />}
                <div className="flex items-center justify-between text-[13px] text-ink">
                  <span>Call {c.id}, number {c.customer.replace('…', 'ending ')}</span>
                  <span className="text-[11.5px] font-normal text-faint">{c.scenario}</span>
                </div>
                <div className="mt-1 flex flex-wrap gap-1">
                  {c.tags.map((tag) => (
                    <Tag key={tag} tone="outline">{tag}</Tag>
                  ))}
                </div>
              </button>
            )
          })}
        </nav>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 flex-shrink-0 items-center justify-between border-b border-line px-6">
          <div className="text-[14px] font-medium text-ink">Call {call.id}, {call.channel}</div>
          <div className="text-[12px] text-muted">Select an assistant turn to review it</div>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[720px] space-y-5 px-6 py-8">
            {call.turns.map((t) => {
              const selectable = Boolean(t.detail)
              const selected = t.id === turn.id
              return (
                <div
                  key={t.id}
                  onClick={selectable ? () => setTurnId(t.id) : undefined}
                  className={`relative rounded-md px-3 py-2 ${selectable ? 'cursor-pointer hover:bg-hover' : ''}`}
                >
                  {selected && <span className="absolute -left-1 top-2 h-[calc(100%-16px)] w-0.5 rounded-full bg-accent" />}
                  <MessageBubble turn={t} perspective="staff" />
                </div>
              )
            })}
          </div>
        </div>
      </main>

      <aside className="hidden w-[380px] flex-shrink-0 flex-col border-l border-line lg:flex xl:w-[440px]">
        <div className="flex h-14 flex-shrink-0 items-center border-b border-line px-5 text-[13px] font-medium text-ink">
          Assistant turn {turnNumber}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <Tabs tabs={TABS} active={tab} onChange={setTab} />

          {tab === 'evidence' && (
            <div className="space-y-6">
              <Block title="Brief lines used">
                {detail.used_brief_lines.length ? (
                  <div className="flex flex-wrap gap-1.5">
                    {detail.used_brief_lines.map((id) => (
                      <button key={id} type="button" className="rounded border border-line px-2 py-0.5 text-[12px] text-ink hover:bg-hover" title="Opens the fact, and from there the turn of the earlier call that produced it">
                        {id}
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="text-[12.5px] text-faint">None cited.</p>
                )}
              </Block>

              <Block title="Tool calls">
                {detail.tool_calls.length ? (
                  <ul className="space-y-2">
                    {detail.tool_calls.map((c, i) => (
                      <li key={i} className="rounded border border-line px-2 py-1.5 font-mono text-[11px] leading-snug">
                        <div className="font-semibold text-ink">{c.name}</div>
                        <div className="text-muted">{JSON.stringify(c.args)}</div>
                        <div className="mt-1 whitespace-pre-wrap break-all text-faint">{c.result}</div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-[12.5px] text-faint">No tool called this turn.</p>
                )}
              </Block>

              <Block title="Guard verdict">
                <Kv rows={[['guard_hard', detail.guard.hard], ['guard_soft', detail.guard.soft]]} />
                {detail.guard.blocked_draft && (
                  <div className="mt-3">
                    <Notice>
                      <span className="text-muted">Blocked draft: </span>
                      {detail.guard.blocked_draft}
                    </Notice>
                  </div>
                )}
              </Block>
            </div>
          )}

          {tab === 'trace' && (
            <div className="space-y-4">
              <Kv
                rows={[
                  ['Prompt', detail.trace.prompt],
                  ['Tokens', `${detail.trace.prompt_tokens} in, ${detail.trace.reply_tokens} out`],
                  ['Latency', `${detail.trace.latency_ms} ms`],
                  ['Cost', `$${detail.trace.cost_usd}`],
                ]}
              />
              <a href={detail.trace.langfuse} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[13px] text-accent hover:underline">
                Open the full trace in Langfuse <ExternalLink size={13} />
              </a>
              <p className="text-[12px] leading-relaxed text-faint">Rendered from our own tables and the Langfuse public API, never an embedded Langfuse page.</p>
            </div>
          )}

          {tab === 'rubric' && (
            <div>
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="text-left text-[12px] text-muted">
                    <th className="py-1 font-medium">Item</th>
                    <th className="py-1 text-center font-medium">Judge</th>
                    <th className="py-1 text-center font-medium">You</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.rubric.map((item) => (
                    <tr key={item.id} className="border-t border-line">
                      <td className="py-2 pr-2 text-ink">{item.label}</td>
                      <td className="py-2 text-center">
                        <Tag tone={item.machine ? 'accent' : 'red'}>{item.machine ? 'Pass' : 'Fail'}</Tag>
                      </td>
                      <td className="py-2 text-center">
                        <input
                          type="checkbox"
                          checked={scores[key(item)] ?? item.machine}
                          onChange={(e) => setScores({ ...scores, [key(item)]: e.target.checked })}
                          className="h-4 w-4 accent-[#2F5D8A]"
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Note for the feedback inbox"
                rows={2}
                className="mt-4 w-full rounded-md border border-line px-3 py-2 text-[13px] text-ink placeholder:text-faint outline-none focus:border-accent"
              />
              {verdict ? (
                <p className="mt-3 text-[12.5px] leading-relaxed text-muted">
                  Sample {verdict} by you. Your scores go to human_scores; agreement with the judge is reported as Cohen's kappa.
                </p>
              ) : (
                <div className="mt-3 flex gap-2">
                  <Button variant="primary" size="sm" onClick={() => setVerdict('approved')}>Approve sample</Button>
                  <Button variant="danger" size="sm" onClick={() => setVerdict('rejected')}>Reject</Button>
                </div>
              )}
            </div>
          )}
        </div>
      </aside>
    </div>
  )
}

function Block({ title, children }) {
  return (
    <section>
      <h3 className="mb-2 text-[13px] font-medium text-ink">{title}</h3>
      {children}
    </section>
  )
}
