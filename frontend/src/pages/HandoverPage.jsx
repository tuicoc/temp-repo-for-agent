// Shift handover: docs/flow.md section 13.4. One query, presented as a list —
// the callbacks due in the coming shift, each with a brief rendered on the
// spot by the same function the agent uses, plus the handoffs still open.
// The point to make: the brief is a function of the ledger, not of the
// person who took the first call, so a colleague leaving costs nothing. Mock.

import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Card, Page, Tag } from '../components/ui'
import { callbacks, handoffs } from '../mock/data'

export function HandoverPage() {
  const [open, setOpen] = useState(callbacks[0].id)

  return (
    <Page title="Shift handover" subtitle="What the next shift has to pick up, with the brief for each so nobody listens to a recording." sample>
      <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
        <Card title="Callbacks due">
          <ul className="divide-y divide-line">
            {callbacks.map((cb) => {
              const expanded = open === cb.id
              return (
                <li key={cb.id} className="py-2">
                  <button type="button" onClick={() => setOpen(expanded ? null : cb.id)} className="flex w-full items-start gap-3 rounded-lg px-2 py-1.5 text-left hover:bg-hover">
                    <span className="mt-1 text-faint">{expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2 text-[13px] text-ink">
                        <span className="font-medium">{cb.due}</span>
                        <span>{cb.customer}</span>
                        <Tag tone="outline">{cb.channel}</Tag>
                        <span className="ml-auto font-mono text-[11px] text-faint">{cb.id}</span>
                      </span>
                      <span className="block text-[12.5px] text-muted">{cb.reason}</span>
                    </span>
                  </button>
                  {expanded && (
                    <ol className="ml-9 mt-1 space-y-1 rounded-lg border border-line px-3 py-2">
                      {cb.brief.map((line, i) => (
                        <li key={i} className="flex gap-2 text-[12.5px] leading-snug text-ink">
                          <span className="w-6 flex-shrink-0 font-mono text-[11px] text-faint">B{i + 1}</span>
                          <span>{line}</span>
                        </li>
                      ))}
                    </ol>
                  )}
                </li>
              )
            })}
          </ul>
        </Card>

        <Card title="Open handoffs">
          {handoffs.map((h) => (
            <div key={h.id} className="rounded-lg border border-line p-3">
              <div className="flex items-center justify-between text-[12.5px]">
                <span className="font-medium text-ink">Call #{h.call_id} · {h.customer}</span>
                <Tag tone="outline">{h.status}</Tag>
              </div>
              <p className="mt-1 text-[12px] text-muted">{h.reason}</p>
              <ul className="mt-2 space-y-1 text-[11.5px] text-muted">
                {h.brief.map((line, i) => <li key={i}>· {line}</li>)}
              </ul>
              <p className="mt-2 text-[11px] text-faint">since {h.at} · accept from the Console</p>
            </div>
          ))}
        </Card>
      </div>
    </Page>
  )
}
