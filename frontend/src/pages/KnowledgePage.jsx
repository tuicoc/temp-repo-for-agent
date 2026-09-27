// Knowledge and feedback. What the assistant is allowed to say about policy
// and product, and what people have said about what it did.
//
// The page is built around how it is used: write or edit an entry, send the
// change for approval, the assistant answers from the approved version. That
// is a sequence, so it is numbered. Entries are question-and-answer pairs
// because that is how the assistant reads them at M1, as one block in its
// prompt; a searchable knowledge base with uploaded documents arrives at M2.
// Sample data throughout.

import { useState } from 'react'
import { Plus } from 'lucide-react'
import { Button, Card, Notice, Page, Table, Tabs, Tag, inputClass } from '../components/ui'
import { faqDiff, faqEntries as initialEntries, faqVersions, feedback } from '../mock/data'

const TABS = [
  { id: 'entries', label: 'Entries' },
  { id: 'versions', label: 'Versions' },
  { id: 'feedback', label: 'Feedback inbox' },
]

const STEPS = [
  { n: 1, title: 'Write or edit an entry', text: 'A question the customer asks, and the answer the assistant may give. Prices never go here; they come from the catalogue.' },
  { n: 2, title: 'Send it for approval', text: 'A change is a draft until someone approves it on the Improvement page. Nothing reaches the assistant unapproved.' },
  { n: 3, title: 'The assistant uses the approved version', text: 'Every reply reads the active version. Roll back by choosing an earlier version.' },
]

const TYPE_LABEL = { thumbs_down: 'Rejected suggestion', note: 'Reviewer note', signal: 'Automatic signal' }

export function KnowledgePage() {
  const [tab, setTab] = useState('entries')
  const [entries, setEntries] = useState(initialEntries)
  const [editing, setEditing] = useState(null)
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState({ question: '', answer: '' })
  const active = faqVersions.find((v) => v.active)

  function saveNew() {
    if (!draft.question.trim() || !draft.answer.trim()) return
    setEntries((list) => [
      { id: `E-${String(list.length + 1).padStart(2, '0')}`, topic: 'New', question: draft.question.trim(), answer: draft.answer.trim(), version: 'draft' },
      ...list,
    ])
    setDraft({ question: '', answer: '' })
    setAdding(false)
  }

  function saveEdit(id, answer) {
    setEntries((list) => list.map((e) => (e.id === id ? { ...e, answer, version: 'draft' } : e)))
    setEditing(null)
  }

  const drafts = entries.filter((e) => e.version === 'draft').length

  return (
    <Page
      title="Knowledge and feedback"
      subtitle="What the assistant is allowed to say about policy and product, and what people have said about what it did."
      sample
      actions={
        <Button variant="primary" onClick={() => { setTab('entries'); setAdding(true) }}>
          <Plus size={14} /> New entry
        </Button>
      }
    >
      <ol className="mb-8 grid gap-6 border-b border-line pb-8 sm:grid-cols-3">
        {STEPS.map((step) => (
          <li key={step.n} className="flex gap-3">
            <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-accent text-[12px] font-medium text-white">{step.n}</span>
            <div>
              <div className="text-[13px] font-medium text-ink">{step.title}</div>
              <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted">{step.text}</p>
            </div>
          </li>
        ))}
      </ol>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      {tab === 'entries' && (
        <div className="grid gap-8 lg:grid-cols-[1fr_300px]">
          <div className="space-y-3">
            {drafts > 0 && (
              <Notice>
                {drafts} {drafts === 1 ? 'entry is' : 'entries are'} in draft and not yet used by the assistant. Approve them on the Improvement page to publish version v2.
              </Notice>
            )}

            {adding && (
              <div className="rounded-md border border-accent p-4">
                <div className="mb-3 text-[13px] font-medium text-ink">New entry</div>
                <label className="mb-3 block">
                  <span className="mb-1 block text-[12px] text-muted">Question the customer asks</span>
                  <input value={draft.question} onChange={(e) => setDraft({ ...draft, question: e.target.value })} className={inputClass} placeholder="Ví dụ: Máy có lọc được mùi thuốc lá không?" />
                </label>
                <label className="mb-3 block">
                  <span className="mb-1 block text-[12px] text-muted">Answer the assistant may give</span>
                  <textarea value={draft.answer} onChange={(e) => setDraft({ ...draft, answer: e.target.value })} rows={3} className={inputClass} placeholder="Câu trả lời ngắn, đúng chính sách. Không ghi giá." />
                </label>
                <div className="flex gap-2">
                  <Button variant="primary" size="sm" onClick={saveNew}>Save as draft</Button>
                  <Button variant="ghost" size="sm" onClick={() => setAdding(false)}>Cancel</Button>
                </div>
              </div>
            )}

            {entries.map((entry) => (
              <div key={entry.id} className="rounded-md border border-line p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-[13.5px] font-medium text-ink">{entry.question}</div>
                    <div className="mt-0.5 text-[12px] text-muted">{entry.topic}</div>
                  </div>
                  <Tag tone={entry.version === 'draft' ? 'outline' : 'accent'}>{entry.version === 'draft' ? 'Draft' : `In ${entry.version}`}</Tag>
                </div>
                {editing === entry.id ? (
                  <EditAnswer initial={entry.answer} onSave={(answer) => saveEdit(entry.id, answer)} onCancel={() => setEditing(null)} />
                ) : (
                  <>
                    <p className="mt-2 text-[13px] leading-[1.6] text-ink">{entry.answer}</p>
                    <div className="mt-2">
                      <Button variant="ghost" size="sm" onClick={() => setEditing(entry.id)}>Edit answer</Button>
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>

          <div className="space-y-6">
            <Card plain title="Where this is used">
              <p className="text-[13px] leading-relaxed text-muted">
                The active version, {active.version}, is placed in the assistant's prompt on every turn, after the rules and the Call Brief and before anything optional. When the prompt is full it is the first thing trimmed, so entries stay short.
              </p>
            </Card>
            <Card plain title="Documents">
              <p className="text-[13px] leading-relaxed text-muted">
                Uploading a policy document, splitting it into passages and searching them per question arrives at M2. Until then the entries on the left are the whole of what the assistant knows.
              </p>
              <Button size="sm" className="mt-3" disabled>Upload a document</Button>
            </Card>
          </div>
        </div>
      )}

      {tab === 'versions' && (
        <div className="grid gap-8 lg:grid-cols-[1fr_1fr]">
          <Card plain title="Versions">
            <Table
              columns={[
                { key: 'version', label: 'Version', mono: true },
                { key: 'entries', label: 'Entries', align: 'right' },
                { key: 'approved_by', label: 'Approved by' },
                { key: 'at', label: 'When' },
                { key: 'active', label: '', render: (r) => (r.active ? <Tag tone="accent">Active</Tag> : <Button size="sm" variant="ghost">Make active</Button>) },
              ]}
              rows={faqVersions}
              keyField="version"
            />
          </Card>
          <Card plain title="What v1 changed from v0">
            <div className="rounded-md border border-line py-1 font-mono text-[11.5px] leading-relaxed">
              {faqDiff.map((line, i) => (
                <div key={i} className={`px-3 py-0.5 ${line.kind === 'add' ? 'bg-accent-tint text-accent' : 'text-muted'}`}>
                  <span className="mr-2 select-none">{line.kind === 'add' ? '+' : ' '}</span>
                  {line.text}
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}

      {tab === 'feedback' && (
        <Card plain title="Everything a person said about a turn" extra="each row can become an entry above">
          <Table
            columns={[
              { key: 'type', label: 'Kind', render: (r) => <Tag tone="outline">{TYPE_LABEL[r.type]}</Tag> },
              { key: 'text', label: 'What' },
              { key: 'call', label: 'Turn', render: (r) => <a href="#/qa" className="text-[12.5px] text-accent hover:underline">Call {r.call}, turn {r.turn}</a> },
              { key: 'at', label: 'When' },
              { key: 'id', label: '', render: () => <Button size="sm" variant="ghost">Turn into an entry</Button> },
            ]}
            rows={feedback}
          />
        </Card>
      )}
    </Page>
  )
}

function EditAnswer({ initial, onSave, onCancel }) {
  const [value, setValue] = useState(initial)
  return (
    <div className="mt-2">
      <textarea value={value} onChange={(e) => setValue(e.target.value)} rows={3} className={inputClass} />
      <div className="mt-2 flex gap-2">
        <Button variant="primary" size="sm" onClick={() => onSave(value)}>Save as draft</Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  )
}
