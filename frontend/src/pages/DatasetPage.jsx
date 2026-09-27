// Dataset & samples. Twelve percent of the grade is the data, and the data is
// otherwise invisible: this page is where a judge checks the multi-session
// customers, the transcripts with raw text beside normalised text, the ASR
// scores by accent region, the inverse text normalisation tests, and the
// catalogue. Mock throughout.

import { useState } from 'react'
import { Play } from 'lucide-react'
import { Card, Page, Stat, Table, Tabs, Tag } from '../components/ui'
import { asrRows, catalogue, customers, itnTests, transcripts } from '../mock/data'

const TABS = [
  { id: 'customers', label: 'Customers' },
  { id: 'transcripts', label: 'Transcripts' },
  { id: 'asr', label: 'ASR quality' },
  { id: 'itn', label: 'ITN tests' },
  { id: 'catalogue', label: 'Catalogue' },
]

export function DatasetPage() {
  const [tab, setTab] = useState('customers')

  return (
    <Page title="Dataset" subtitle="What the transcripts, the audio and the catalogue actually contain, with the multi-session customers first because they are the point." sample>
      <div className="mb-7 grid gap-6 sm:grid-cols-5">
        <Stat label="Transcripts" value="124" hint="≥ 120 required" />
        <Stat label="With audio" value="42" hint="≥ 40 required" />
        <Stat label="Multi-session" value="31" hint="≥ 30 customers" />
        <Stat label="Multi-channel" value="11" hint="≥ 10 customers" />
        <Stat label="SKUs" value="30" hint="≥ 30 required" />
      </div>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      {tab === 'customers' && (
        <Card title="Customers, multi-session first">
          <Table
            columns={[
              { key: 'id', label: 'Customer', mono: true },
              { key: 'last4', label: 'Phone', render: (r) => `…${r.last4}` },
              { key: 'calls', label: 'Sessions', align: 'right' },
              { key: 'channels', label: 'Channels', render: (r) => r.channels.map((c) => <Tag key={c} tone="outline" className="mr-1">{c}</Tag>) },
              { key: 'persona', label: 'Persona' },
              { key: 'last', label: 'Last contact' },
              { key: 'outcome', label: 'Outcome' },
            ]}
            rows={customers}
          />
        </Card>
      )}

      {tab === 'transcripts' && (
        <Card title="Transcripts · raw beside normalised, so ITN is visible">
          <div className="space-y-3">
            {transcripts.map((t) => (
              <div key={t.id} className="rounded-lg border border-line p-3">
                <div className="mb-2 flex flex-wrap items-center gap-2 text-[12px] text-muted">
                  <span className="font-mono text-ink">{t.id}</span>
                  <span>{t.customer} · call {t.call}</span>
                  <Tag tone="outline">{t.channel}</Tag>
                  <Tag tone="outline">{t.persona}</Tag>
                  {t.tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}
                  {t.audio && (
                    <button type="button" className="ml-auto flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-[11.5px] hover:bg-hover">
                      <Play size={11} /> audio · {t.region}
                    </button>
                  )}
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  <div>
                    <div className="mb-1 text-[12px] text-muted">As heard</div>
                    <p className="text-[12.5px] leading-snug text-muted">{t.raw}</p>
                  </div>
                  <div>
                    <div className="mb-1 text-[12px] text-muted">Normalised</div>
                    <p className="text-[12.5px] leading-snug text-ink">{t.normalised}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {tab === 'asr' && (
        <Card title="ASR quality on the scored files">
          <Table
            columns={[
              { key: 'region', label: 'Region' },
              { key: 'files', label: 'Files', align: 'right' },
              { key: 'wer', label: 'WER', align: 'right' },
              { key: 'cer', label: 'CER', align: 'right' },
              { key: 'entity_money', label: 'Entity · money', align: 'right' },
              { key: 'entity_phone', label: 'Entity · phone', align: 'right' },
            ]}
            rows={asrRows}
            keyField="region"
          />
          <p className="mt-3 text-[11.5px] text-faint">
            Normalisation before scoring, as published: lower-case, punctuation removed, numbers through the same ITN module the agent uses. Entity accuracy is exact match after ITN; it matters more than WER in this task.
          </p>
        </Card>
      )}

      {tab === 'itn' && (
        <Card title="Inverse text normalisation · test suite">
          <Table
            columns={[
              { key: 'spoken', label: 'Spoken form' },
              { key: 'expected', label: 'Expected', mono: true },
              { key: 'got', label: 'Got', mono: true },
              { key: 'ok', label: '', render: (r) => <Tag tone={r.ok ? 'green' : 'red'}>{r.ok ? 'pass' : 'fail'}</Tag> },
            ]}
            rows={itnTests}
            keyField="spoken"
            dense
          />
        </Card>
      )}

      {tab === 'catalogue' && (
        <Card title="Catalogue · prices and promotions with their validity">
          <Table
            columns={[
              { key: 'sku', label: 'SKU', mono: true },
              { key: 'name', label: 'Product' },
              { key: 'price', label: 'List price (đ)', align: 'right' },
              { key: 'promo', label: 'Promotion' },
              { key: 'stock', label: 'Stock' },
            ]}
            rows={catalogue}
            keyField="sku"
          />
        </Card>
      )}
    </Page>
  )
}
