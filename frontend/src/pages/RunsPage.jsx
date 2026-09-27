// Runs and metrics. The rule from the working notes: this page displays what
// a run wrote and never computes anything. Every section is drawn the same
// way, a title on a rule and the content under it, and each figure appears
// twice: in a chart to see the gap, in a table to read the number.
// Sample data until the evaluation runner exists.

import { Card, Kv, Page, Stat, Table, Tag } from '../components/ui'
import { GroupedBars, RoundsLine } from '../components/Charts'
import { compareRefusal, failedCases, latency, manifest, metrics, rounds } from '../mock/data'

const pct = (v) => `${Math.round(v)}%`
const sec = (v) => `${v.toFixed(1)} s`

const COMPARISON = [
  { label: 'Repeat-question', a: 58.3, b: 21.4 },
  { label: 'Context carryover', a: 12.5, b: 78.9 },
  { label: 'Task success', a: 45.5, b: 77.3 },
  { label: 'Hallucination', a: 9.1, b: 1.8 },
]

const LATENCY = [
  { label: 'First token', a: 0.41, b: 0.92 },
  { label: 'First content', a: 2.8, b: 6.4 },
  { label: 'Brief load', a: 0.9, b: 1.7 },
]

export function RunsPage() {
  return (
    <Page
      title="Runs and metrics"
      subtitle="One command prints this table. The page shows what the run wrote and computes nothing itself, so no number here is ever typed by hand."
      sample
      actions={<Tag tone="outline">{manifest.run_name}</Tag>}
    >
      <div className="mb-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {latency.map((item) => (
          <Stat key={item.label} label={item.label} value={item.value} hint={item.hint} />
        ))}
      </div>

      <div className="space-y-10">
        <Card plain title="Baseline against the system" extra={`golden set, ${manifest.golden_set.scenarios} scenarios`}>
          <div className="grid gap-8 lg:grid-cols-[1fr_1fr]">
            <GroupedBars groups={COMPARISON} series={['Baseline, no memory', 'System']} max={100} format={pct} />
            <div>
              <Table
                columns={[
                  { key: 'metric', label: 'Metric', render: (r) => <span className={r.star ? 'font-medium' : ''}>{r.metric}</span> },
                  { key: 'baseline', label: 'Baseline', align: 'right' },
                  { key: 'system', label: 'System', align: 'right' },
                  { key: 'delta', label: 'Difference', align: 'right' },
                ]}
                rows={metrics}
                keyField="metric"
              />
              <p className="mt-3 text-[12px] leading-relaxed text-faint">
                Same test set, model and parameters; the only difference is the memory switch at retrieve. Threshold for repeat-question rate: at least 40% relative reduction.
              </p>
            </div>
          </div>
        </Card>

        <Card plain title="Repeat-question rate across rounds" extra="frozen golden set, same manifest except versions">
          <div className="grid gap-8 lg:grid-cols-[1fr_1fr]">
            <RoundsLine
              points={[
                { label: 'R0, faq v0', value: 24.1 },
                { label: 'R1, faq v1', value: 21.4 },
              ]}
              references={[
                { label: 'baseline', value: 58.3 },
                { label: 'threshold', value: 35.0 },
              ]}
              format={pct}
            />
            <Table
              columns={[
                { key: 'metric', label: 'Metric' },
                { key: 'r0', label: 'R0, faq v0', align: 'right' },
                { key: 'r1', label: 'R1, faq v1', align: 'right' },
                { key: 'r2', label: 'R2, exemplars', align: 'right' },
              ]}
              rows={rounds}
              keyField="metric"
            />
          </div>
        </Card>

        <Card plain title="Latency, p50 against p95" extra="seconds, from the timers in the reply">
          <div className="grid gap-8 lg:grid-cols-[1fr_1fr]">
            <GroupedBars groups={LATENCY} series={['p50', 'p95']} max={8} format={sec} height={200} />
            <p className="max-w-[420px] text-[13px] leading-relaxed text-muted">
              First token is when the page stopped looking frozen; first content is when the customer could read an answer the guard had passed. Both are reported because the first alone would flatter the system. The brief has to load within five seconds at M1.
            </p>
          </div>
        </Card>

        <Card plain title="Failed cases" extra="errors.jsonl, each opens in QA review">
          <Table
            columns={[
              { key: 'id', label: 'Scenario', mono: true },
              { key: 'metric', label: 'Metric', render: (r) => <Tag tone="outline">{r.metric}</Tag> },
              { key: 'reason', label: 'What went wrong' },
              { key: 'call_id', label: '', render: (r) => <a href="#/qa" className="text-[12.5px] text-accent hover:underline">Open call {r.call_id}</a> },
            ]}
            rows={failedCases}
          />
        </Card>

        <Card plain title="Compare" extra="eval compare r0 r1">
          <pre className="whitespace-pre-wrap rounded-md border border-line px-3 py-2.5 font-mono text-[11.5px] leading-relaxed text-ink">{compareRefusal}</pre>
          <p className="mt-2 text-[12px] text-faint">A refusal is shown on purpose: it is the proof that a comparison between runs is policed by code.</p>
        </Card>

        <Card plain title="Manifest" extra="written by the runner">
          <div className="max-w-[640px]">
            <Kv
              rows={[
                ['Run', manifest.run_id],
                ['Commit', `${manifest.git.commit}${manifest.git.dirty ? ', dirty tree' : ''}`],
                ['Hot model', manifest.models.hot],
                ['Cold model', manifest.models.cold],
                ['Judge', manifest.models.judge],
                ['Embeddings', manifest.models.embed],
                ['FAQ version', manifest.versions.faq],
                ['Switches', JSON.stringify(manifest.switches)],
                ['Temperature', String(manifest.generation.temperature)],
                ['Cache hit rate', `${Math.round(manifest.cache.hit_rate * 100)}%`],
                ['Golden set', manifest.golden_set.sha256],
                ['Catalogue snapshot', manifest.golden_set.catalog_snapshot],
              ]}
            />
          </div>
        </Card>
      </div>
    </Page>
  )
}
