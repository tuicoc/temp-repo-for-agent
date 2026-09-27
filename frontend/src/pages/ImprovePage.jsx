// Improvement: docs/flow.md section 18's review gate, which at this scale is
// one page with two buttons. Proposals come from clustered signals; a person
// approves, rejects or edits the answer; an approved proposal becomes the
// next FAQ version and adds its test case to the growth set — never to the
// golden set, and the page says which. Mock.

import { useState } from 'react'
import { Check, RotateCcw, X } from 'lucide-react'
import { Button, Card, Page, Table, Tag } from '../components/ui'
import { faqVersions, proposals as initial } from '../mock/data'

export function ImprovePage() {
  const [proposals, setProposals] = useState(initial)
  const [editing, setEditing] = useState(null)

  function decide(id, status) {
    setProposals((list) => list.map((p) => (p.id === id ? { ...p, status } : p)))
    setEditing(null)
  }

  return (
    <Page
      title="Improvement"
      subtitle="Signals become proposals, a person decides, the decision becomes a version. Nothing changes what the assistant says without a name next to it."
      sample
    >
      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        <div className="space-y-3">
          {proposals.map((p) => (
            <Card key={p.id} title={p.cluster} extra={
              <div className="flex items-center gap-2 text-[11px] text-faint">
                <span className="font-mono">{p.id}</span>
                <span>{p.count} signals · from {p.source}</span>
                <Tag tone={p.status === 'approved' ? 'green' : p.status === 'rejected' ? 'red' : 'neutral'}>{p.status}</Tag>
              </div>
            }>
              <div className="mb-3 space-y-1">
                {p.examples.map((e, i) => (
                  <p key={i} className="text-[12.5px] italic text-muted">“{e}”</p>
                ))}
              </div>
              {editing === p.id ? (
                <textarea
                  defaultValue={p.draft}
                  rows={3}
                  className="w-full rounded-md border border-line px-3 py-2 text-[13px] text-ink outline-none focus:border-accent"
                />
              ) : (
                <p className="rounded-lg border border-line px-3 py-2 text-[13px] leading-[1.6] text-ink">{p.draft}</p>
              )}
              {p.status === 'pending' ? (
                <div className="mt-3 flex gap-2">
                  <Button variant="primary" size="sm" onClick={() => decide(p.id, 'approved')}><Check size={13} /> Approve</Button>
                  <Button size="sm" onClick={() => setEditing(editing === p.id ? null : p.id)}>{editing === p.id ? 'Done editing' : 'Edit answer'}</Button>
                  <Button variant="danger" size="sm" onClick={() => decide(p.id, 'rejected')}><X size={13} /> Reject</Button>
                </div>
              ) : (
                <p className="mt-3 text-[12px] text-faint">
                  {p.status === 'approved'
                    ? 'Approved. Goes into faq v2 on apply; its test case joins the growth set, not the golden set.'
                    : 'Rejected. Kept as a signal, not applied.'}
                </p>
              )}
            </Card>
          ))}
        </div>

        <div className="space-y-4">
          <Card title="FAQ versions">
            <Table
              columns={[
                { key: 'version', label: 'Version', mono: true },
                { key: 'entries', label: 'Entries', align: 'right' },
                { key: 'approved_by', label: 'Approved by' },
                { key: 'active', label: '', render: (r) => (r.active ? <Tag tone="ink">active</Tag> : <Button size="sm" variant="ghost"><RotateCcw size={12} /> Roll back</Button>) },
              ]}
              rows={faqVersions}
              keyField="version"
              dense
            />
            <p className="mt-3 text-[11.5px] text-faint">
              Rollback moves a pointer. It runs by itself when eval compare shows RQR up, TSR down, or HR on price above 5% against the previous round.
            </p>
          </Card>

          <Card title="Where a case goes">
            <ul className="space-y-1.5 text-[12.5px] text-ink">
              <li className="flex justify-between"><span>Golden set</span><span className="font-mono text-muted">22 · frozen</span></li>
              <li className="flex justify-between"><span>Growth set</span><span className="font-mono text-muted">7 · +1 on approve</span></li>
              <li className="flex justify-between"><span>ASR eval</span><span className="font-mono text-muted">20 files</span></li>
            </ul>
          </Card>
        </div>
      </div>
    </Page>
  )
}
