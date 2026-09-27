// Admin: what this process runs on, and how fast it answers.
//
// The advisor's model, the voice channel's recogniser, endpointing and
// voice, and the business day calls run on can all be changed here for this
// process; a restart returns to config/models.yaml. The latency figures are
// the organisers' four (eval/huong-dan-do-latency.md), p50 and p95 over the
// turns recorded, warm-up excluded. The memory switch is shown, not offered:
// it is an evaluation control. The health report is the service's own.

import { useEffect, useState } from 'react'
import { api } from '../services/api'
import { Button, Card, Notice, Page, Table, Tag, inputClass } from '../components/ui'

export function AdminPage() {
  const [health, setHealth] = useState(null)

  useEffect(() => {
    fetch('/health')
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth({ status: 'unreachable' }))
  }, [])

  return (
    <Page title="Admin" subtitle="The models this process runs on, the business day, and the timings the organisers grade. Changes last until the service restarts.">
      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        <div className="space-y-8">
          <Card title="Advisor model" extra="this process only; a restart returns to config/models.yaml" plain>
            <AdvisorModel />
          </Card>

          <Card title="Voice channel" extra="for calls placed from now on" plain>
            <VoiceSettings />
          </Card>

          <Card title="Latency" extra="measured at the API, warm-up excluded" plain>
            <Latency />
          </Card>
        </div>

        <div className="space-y-6">
          <Card title="Business day">
            <BusinessDay />
          </Card>

          <Card title="Memory switch">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[13px] text-ink">switches.memory</div>
                <div className="text-[12px] text-muted">Off is the baseline.</div>
              </div>
              <Tag tone="accent">On</Tag>
            </div>
            <div className="mt-3">
              <Notice>An evaluation control. The runner sets it per run; it is never flipped during a live conversation.</Notice>
            </div>
          </Card>

          <Card title="Delete a customer">
            <p className="text-[12.5px] leading-relaxed text-muted">Removes the customer's profile, episodes, identities and vault rows (policy QT-06). The server side exists as memory.delete_customer; this form is not wired to it yet.</p>
            <div className="mt-3 flex gap-2">
              <input placeholder="customer id" className="h-8 flex-1 rounded-md border border-line px-3 text-[12px] outline-none" disabled />
              <Button variant="danger" size="sm" disabled>Delete</Button>
            </div>
          </Card>

          <Card title="Health" extra="GET /health, live">
            {health ? <Health report={health} /> : <p className="text-[12.5px] text-faint">Asking the service.</p>}
          </Card>
        </div>
      </div>
    </Page>
  )
}

function Health({ report }) {
  const components = report.components || {}
  const rows = [
    ['Service', report.status, report.version ? `version ${report.version}, up ${Math.round((report.uptime_seconds || 0) / 60)} min` : report.startup_error],
    ['Database', components.database?.status, components.database?.detail],
    ['Checkpointer', components.checkpointer?.status],
    ['Assistant', components.agent?.status, components.agent?.model],
    ['Voice', components.voice?.status, components.voice?.hint || (components.voice?.status === 'ok' ? 'local ASR, VAD and TTS installed' : null)],
    ['Tracing', components.tracing?.status],
  ]
  const mcp = components.mcp || {}
  Object.entries(mcp).forEach(([role, info]) => {
    if (info?.tools) rows.push([`Tools for ${role}`, info.status, `${info.tools.length} over ${info.transport}: ${info.tools.join(', ')}`])
  })
  if (mcp.status) rows.push(['Tools', mcp.status])
  const sessions = report.sessions
  return (
    <div>
      <ul className="space-y-2">
        {rows.map(([label, state, detail]) => {
          const good = ['ok', 'on', 'connected'].includes(state)
          return (
            <li key={label} className="grid grid-cols-[112px_1fr] gap-3 text-[13px]">
              <span className="flex items-center gap-2 text-muted">
                <span className={`h-2 w-2 flex-shrink-0 rounded-full ${good ? 'bg-accent' : state === 'off' ? 'bg-line-2' : 'bg-danger'}`} />
                {label}
              </span>
              <span className="min-w-0 break-words text-ink">
                {state}
                {detail && <span className="text-muted">, {detail}</span>}
              </span>
            </li>
          )
        })}
      </ul>
      {sessions && (
        <p className="mt-3 border-t border-line pt-3 text-[12.5px] text-muted">
          {sessions.open} open {sessions.open === 1 ? 'session' : 'sessions'}, {sessions.today} started today, {sessions.handoffs_waiting} waiting for a consultant.
        </p>
      )}
    </div>
  )
}

function AdvisorModel() {
  const [settings, setSettings] = useState(null)
  const [choice, setChoice] = useState('')
  const [temperature, setTemperature] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  function show(s) {
    setSettings(s)
    setChoice(`${s.provider}::${s.model}`)
    setTemperature(s.temperature == null ? '' : String(s.temperature))
  }

  useEffect(() => {
    api.advisorSettings().then(show).catch((err) => setMessage(err.message || 'Could not load the advisor settings.'))
  }, [])

  async function apply(reset = false) {
    setBusy(true)
    setMessage('')
    try {
      const [provider, model] = choice.split('::')
      const body = reset ? {} : { provider, model, temperature: temperature === '' ? null : Number(temperature) }
      const s = await api.setAdvisor(body)
      show(s)
      setMessage(reset ? 'Back to the routing in the file.' : `The advisor now runs on ${s.model}.`)
    } catch (err) {
      setMessage(err.message || 'Could not change the advisor.')
    } finally {
      setBusy(false)
    }
  }

  if (!settings) return <p className="text-[12.5px] text-faint">{message || 'Loading'}</p>

  const ignoresTemperature = /gemini-3\.5-flash-lite/.test(settings.model || '')

  return (
    <div className="max-w-[560px] space-y-4">
      <div className="grid gap-4 sm:grid-cols-[1fr_140px]">
        <label className="block">
          <span className="mb-1 block text-[12px] text-muted">Model</span>
          <select value={choice} onChange={(e) => setChoice(e.target.value)} className={inputClass}>
            {settings.choices.map((c) => (
              <option key={`${c.provider}::${c.model}`} value={`${c.provider}::${c.model}`}>{c.label}</option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] text-muted">Temperature</span>
          <input type="number" min="0" max="2" step="0.1" value={temperature} onChange={(e) => setTemperature(e.target.value)} placeholder="from file" className={inputClass} />
        </label>
      </div>
      <p className="text-[12.5px] text-muted">
        Running on {settings.model}{settings.temperature != null ? ` at temperature ${settings.temperature}` : ''}{settings.overridden ? ', changed here' : ', from the file'}.
        {ignoresTemperature && ' This model ignores the temperature; reproducibility rests on the cache.'}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" size="sm" disabled={busy} onClick={() => apply(false)}>Apply</Button>
        <Button size="sm" disabled={busy || !settings.overridden} onClick={() => apply(true)}>Reset to file</Button>
        {message && <span className="text-[12.5px] text-muted">{message}</span>}
      </div>
    </div>
  )
}

function VoiceSettings() {
  const [settings, setSettings] = useState(null)
  const [form, setForm] = useState({})
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  function show(s) {
    setSettings(s)
    setForm({ asr: s.asr, endpointing: s.endpointing, barge_in_ms: s.barge_in_ms, min_interruption_words: s.min_interruption_words, tts: s.tts })
  }

  useEffect(() => {
    api.voiceSettings().then(show).catch((err) => setMessage(err.message || 'Could not load the voice settings.'))
  }, [])

  async function apply(body, done) {
    setBusy(true)
    setMessage('')
    try {
      show(await api.setVoice(body))
      setMessage(done)
    } catch (err) {
      setMessage(err.message || 'Could not change the voice settings.')
    } finally {
      setBusy(false)
    }
  }

  async function warm() {
    setBusy(true)
    setMessage('Loading the models; the first voice can take a minute.')
    try {
      const r = await api.warmVoice()
      setMessage(`Loaded ${r.asr} in ${r.asr_load_seconds} s and warmed ${r.tts}. The next call starts without waiting.`)
    } catch (err) {
      setMessage(err.message || 'Could not load the models.')
    } finally {
      setBusy(false)
    }
  }

  if (!settings) return <p className="text-[12.5px] text-faint">{message || 'Loading'}</p>
  const installed = settings.available?.status === 'ok'
  const field = (key) => ({ value: form[key] ?? '', onChange: (e) => setForm((f) => ({ ...f, [key]: e.target.value })) })

  return (
    <div className="max-w-[560px] space-y-4">
      {!installed && <Notice tone="danger">Voice is not installed on this server: {settings.available?.hint}</Notice>}
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-[12px] text-muted">Speech recognition</span>
          <select {...field('asr')} className={inputClass} disabled={!installed}>
            {(settings.asr_choices.length ? settings.asr_choices : [{ name: settings.asr, label: settings.asr }]).map((c) => (
              <option key={c.name} value={c.name}>{c.label}</option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] text-muted">End of the caller's turn</span>
          <select {...field('endpointing')} className={inputClass}>
            {settings.endpointing_choices.map((c) => <option key={c.name} value={c.name}>{c.label}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] text-muted">Voice</span>
          <select {...field('tts')} className={inputClass} disabled={!installed}>
            {settings.tts_choices.map((c) => <option key={c.name} value={c.name}>{c.label}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] text-muted">Pause the answer after (ms of speech)</span>
          <input type="number" min="100" max="2000" step="50" {...field('barge_in_ms')} className={inputClass} />
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] text-muted">Words needed to cut in</span>
          <input type="number" min="0" max="6" step="1" {...field('min_interruption_words')} className={inputClass} />
        </label>
      </div>
      <p className="text-[12.5px] leading-relaxed text-muted">
        Speech over the answer pauses it; once the words are in, fewer than the words needed, or only "ừ", "dạ", "vâng", resumes it, and more stops it. Smart Turn decides from the audio whether a pause ends the caller's turn; silence ends it after a fixed wait.
        {settings.overridden ? ' Changed here, not the file.' : ' From the file.'}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" size="sm" disabled={busy} onClick={() => apply({ ...form, barge_in_ms: Number(form.barge_in_ms), min_interruption_words: Number(form.min_interruption_words) }, 'Calls placed from now on use these.')}>Apply</Button>
        <Button size="sm" disabled={busy || !settings.overridden} onClick={() => apply({ reset: true }, 'Back to the file.')}>Reset to file</Button>
        <Button size="sm" disabled={busy || !installed} onClick={warm}>Load models now</Button>
        {message && <span className="text-[12.5px] text-muted">{message}</span>}
      </div>
    </div>
  )
}

const FIGURES = [
  { key: 'ttft', label: 'Time to first token', note: 'request at the API to the first token of the answer' },
  { key: 'total', label: 'Total', note: 'to the last token' },
  { key: 'ttfa', label: 'Time to first audio', note: 'caller stops speaking to the first audio byte sent' },
  { key: 'call_brief', label: 'Call Brief', note: 'caller identified to the brief ready, refresh included' },
  { key: 'ttfa_client', label: 'First audio, end to end', note: 'as the browser heard it; reported apart' },
]

function Latency() {
  const [report, setReport] = useState(null)
  const [channel, setChannel] = useState('all')
  const [error, setError] = useState('')

  useEffect(() => {
    setError('')
    api.latency(channel).then(setReport).catch((err) => setError(err.message || 'Could not load the timings.'))
  }, [channel])

  if (error) return <p className="text-[12.5px] text-ink">{error}</p>
  if (!report) return <p className="text-[12.5px] text-faint">Loading</p>

  const rows = FIGURES.map((f) => {
    const s = report[f.key]
    const limit = report.thresholds_ms?.[f.key]
    return {
      key: f.key,
      figure: (
        <span>
          <span className="text-ink">{f.label}</span>
          <span className="block text-[12px] text-muted">{f.note}</span>
        </span>
      ),
      n: s ? s.n : 0,
      p50: s ? ms(s.p50_ms) : '',
      p95: s ? <span className={limit && s.p95_ms > limit ? 'text-danger' : 'text-ink'}>{ms(s.p95_ms)}</span> : '',
      limit: limit ? `${ms(limit)}` : '',
    }
  })

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <select value={channel} onChange={(e) => setChannel(e.target.value)} className={`${inputClass} w-[180px]`}>
          <option value="all">Every channel</option>
          <option value="web">Website chat</option>
          <option value="zalo">Zalo</option>
          <option value="hotline">Hotline</option>
        </select>
        <span className="text-[12.5px] text-muted">
          {report.turns} turns, {report.warmup_excluded} warm-up left out.
        </span>
      </div>
      <Table
        keyField="key"
        columns={[
          { key: 'figure', label: 'Figure' },
          { key: 'n', label: 'Turns', align: 'right' },
          { key: 'p50', label: 'p50', align: 'right' },
          { key: 'p95', label: 'p95', align: 'right' },
          { key: 'limit', label: 'p95 limit', align: 'right' },
        ]}
        rows={rows}
      />
      <p className="text-[12.5px] leading-relaxed text-muted">
        Replies are not streamed yet, so the first token is the whole answer and TTFT equals Total (the organisers' rule 7). A p95 above its limit is shown in red.
        {report.warning ? ` ${report.warning}` : ''}
      </p>
    </div>
  )
}

function ms(value) {
  return value == null ? '' : value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${value} ms`
}

function BusinessDay() {
  const [day, setDay] = useState('')
  const [saved, setSaved] = useState('')
  const [message, setMessage] = useState('')

  useEffect(() => {
    api.clock().then((c) => { setDay(c.day); setSaved(c.day) }).catch(() => setMessage('Could not read the day.'))
  }, [])

  async function apply(value) {
    setMessage('')
    try {
      const c = await api.setClock(value)
      setDay(c.day)
      setSaved(c.day)
      setMessage(`Calls placed from now on run on ${c.day}, at 10:00.`)
    } catch (err) {
      setMessage(err.message || 'Could not change the day.')
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-[12.5px] leading-relaxed text-muted">
        The organisers' catalogue, promotions and stock are written for 15 October 2026. Tools answer for this day, not the wall clock. Move it forward to show a customer calling back days later.
      </p>
      <div className="flex gap-2">
        <input type="date" value={day} onChange={(e) => setDay(e.target.value)} className={inputClass} />
        <Button variant="primary" size="sm" disabled={!day || day === saved} onClick={() => apply(day)}>Apply</Button>
      </div>
      <Button size="sm" onClick={() => apply(null)} disabled={saved === '2026-10-15'}>Back to 15 October</Button>
      {message && <p className="text-[12.5px] text-muted">{message}</p>}
    </div>
  )
}
