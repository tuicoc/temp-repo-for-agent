// A simulated hotline call, drawn the way a phone draws one.
//
// Who is on the line and for how long at the top; in the middle, bars that
// follow whoever is talking (the assistant in the accent, the caller in grey)
// and say what the assistant is doing; at the bottom, the three controls a
// call screen has: mute, hang up, and the transcript. The transcript is the
// call's running record, with each answer's time to first audio measured the
// organisers' way, from the moment the caller stopped speaking.
//
// The call itself (VoiceCall) belongs to the page, which created it in the
// click that placed the call; this component only connects it and draws it.

import { useEffect, useRef, useState } from 'react'
import { Headset, MessageSquareText, Mic, MicOff, PhoneOff } from 'lucide-react'
import { BarVisualizer } from './BarVisualizer'

const CAPTION = {
  connecting: 'Connecting',
  loading: 'Connecting the line',
  listening: 'Listening',
  user: 'Listening to you',
  thinking: 'Thinking',
  speaking: 'Speaking',
  ended: 'Call ended',
}

export function CallView({ call, line, onBack }) {
  const [state, setState] = useState('connecting')
  const [lines, setLines] = useState([])
  const [error, setError] = useState('')
  const [seconds, setSeconds] = useState(0)
  const [muted, setMuted] = useState(false)
  const [showTranscript, setShowTranscript] = useState(true)
  const [paused, setPaused] = useState(false)
  const [input, setInput] = useState(null)
  const [mic, setMic] = useState(null)
  const started = useRef(null)
  const bottom = useRef(null)

  useEffect(() => {
    line
      .connect(call.id, (message) => {
        switch (message.type) {
          case 'state':
            if (!mic) setMic(line.microphone())
            setState(message.state)
            if (message.state === 'listening' && started.current == null) started.current = Date.now()
            break
          case 'pause':
            setPaused(true)
            break
          case 'input':
            setInput(message)
            break
          case 'resume':
          case 'stop':
            setPaused(false)
            break
          case 'transcript':
            setLines((list) => [...list, { id: `${message.turn}-caller`, who: 'caller', text: message.text }])
            break
          case 'ignored':
            if (message.text) setLines((list) => [...list, { id: `i-${Date.now()}`, who: 'ignored', text: message.text, why: message.why }])
            break
          case 'reply':
            if (message.waiting) {
              setLines((list) => [...list, { id: `${message.turn}-w`, who: 'note', text: 'A consultant has the call now.' }])
            } else if (message.text) {
              setLines((list) => [...list, { id: `${message.turn}-agent`, who: 'agent', text: message.text, superseded: message.superseded }])
            }
            break
          case 'truncated':
            setLines((list) => list.map((l) => (l.id === `${message.turn}-agent` ? { ...l, heard: message.heard } : l)))
            break
          case 'metrics':
            setLines((list) => list.map((l) => (l.id === `${message.turn}-agent` ? { ...l, metrics: message } : l)))
            break
          case 'error':
            setError(message.text)
            break
          case 'closed':
            setState('ended')
            break
          default:
            break
        }
      })
      .catch((err) => {
        setError(err?.name === 'NotAllowedError' ? 'The browser did not allow the microphone. Allow it for this site and call again.' : String(err?.message || err))
        setState('ended')
      })
  }, [call.id, line])

  useEffect(() => {
    const timer = setInterval(() => {
      if (started.current != null && state !== 'ended') setSeconds(Math.floor((Date.now() - started.current) / 1000))
    }, 500)
    return () => clearInterval(timer)
  }, [state])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines, showTranscript])

  function hangUp() {
    line.hangUp()
    setState('ended')
  }

  function toggleMute() {
    line.setMuted(!muted)
    setMuted(!muted)
  }

  const live = state !== 'ended'
  // The bars follow the caller's own microphone as soon as it hears them, not
  // only once the server has decided they are speaking.
  const heardHere = useLevel(line.micAnalyser) > 0.015 && state !== 'speaking'
  const callerTalking = state === 'user' || paused || (live && heardHere && state !== 'connecting' && state !== 'loading')
  const visual = callerTalking ? 'speaking'
    : state === 'speaking' ? 'speaking'
    : state === 'thinking' ? 'thinking'
    : state === 'loading' ? 'initializing'
    : state === 'connecting' ? 'connecting'
    : live ? 'listening' : 'ended'
  const caption = paused ? 'Listening to you' : CAPTION[state] || CAPTION.listening
  const status = !live ? `Ended, ${clock(seconds)}` : started.current == null ? 'Calling' : clock(seconds)

  return (
    <div className="flex h-full flex-col bg-surface">
      <section className={`flex flex-shrink-0 flex-col items-center px-6 text-center ${showTranscript ? 'pt-10 pb-6' : 'flex-1 justify-center'}`}>
        <div className={`flex h-20 w-20 items-center justify-center rounded-full ${live ? 'bg-accent-tint text-accent' : 'bg-hover text-faint'}`}>
          <Headset size={34} strokeWidth={1.5} />
        </div>
        <h1 className="mt-4 text-[20px] font-semibold leading-tight text-ink">Shop hotline</h1>
        <p className="mt-1 text-[13px] text-muted">From {formatPhone(call.phone)}</p>
        <p className="mt-0.5 text-[13px] tabular-nums text-muted" aria-live="polite">{status}</p>

        <BarVisualizer
          className="mt-6 h-16 w-[160px]"
          state={visual}
          tone={callerTalking ? 'caller' : 'agent'}
          analyser={callerTalking ? line.micAnalyser : line.agentAnalyser}
        />
        <p className="mt-3 text-[13px] text-ink" aria-live="polite">{live ? caption : CAPTION.ended}</p>
        {live && (
          <Microphone
            line={line}
            current={mic}
            input={input}
            onChange={async (id) => {
              await line.useMicrophone(id)
              setMic(line.microphone())
            }}
          />
        )}
        {error && <p role="alert" className="mt-3 max-w-[420px] border-l-2 border-danger pl-3 text-left text-[13px] text-ink">{error}</p>}
      </section>

      {showTranscript && (
        <div className="min-h-0 flex-1 overflow-y-auto border-t border-line">
          <div className="mx-auto w-full max-w-[640px] space-y-4 px-6 py-6">
            {lines.length === 0 && <p className="text-center text-[12.5px] text-faint">What is said on the call appears here.</p>}
            {lines.map((item) => (
              <Line key={item.id} item={item} />
            ))}
            <div ref={bottom} />
          </div>
        </div>
      )}

      <footer className="flex flex-shrink-0 items-start justify-center gap-10 border-t border-line px-6 pb-7 pt-5">
        {live ? (
          <>
            <Control label={muted ? 'Unmute' : 'Mute'} onClick={toggleMute} pressed={muted}>
              {muted ? <MicOff size={20} /> : <Mic size={20} />}
            </Control>
            <Control label="Hang up" onClick={hangUp} tone="end">
              <PhoneOff size={22} />
            </Control>
            <Control label="Transcript" onClick={() => setShowTranscript((v) => !v)} pressed={showTranscript}>
              <MessageSquareText size={20} />
            </Control>
          </>
        ) : (
          <button
            type="button"
            onClick={onBack}
            className="h-9 rounded-md bg-accent px-4 text-[13px] font-medium text-white transition-colors hover:bg-[#274d73]"
          >
            Back
          </button>
        )}
      </footer>
    </div>
  )
}

// The microphone, from both ends: a meter that moves with the sound the
// browser hears, the device it hears it through, and what the server says
// reaches it. Together they tell a muted or wrong microphone (the meter does
// not move), a line that drops audio (the meter moves, the server hears
// nothing) and a quiet voice (the server hears sound but not speech).
function Microphone({ line, current, input, onChange }) {
  const level = useLevel(line.micAnalyser)
  const [devices, setDevices] = useState([])

  useEffect(() => {
    if (current) line.microphones().then(setDevices).catch(() => setDevices([]))
  }, [current, line])

  const hint = !input ? null
    : input.level < 0.002 ? 'Almost no sound reaches the line. Check the microphone is not muted, or choose another.'
    : input.speech_score < 0.5 && input.speech === 0 ? 'Sound arrives but does not sound like speech yet. Speak a little closer to the microphone.'
    : null

  return (
    <div className="mt-5 w-full max-w-[320px] text-left">
      <div className="h-[3px] w-full overflow-hidden rounded-full bg-hover" aria-hidden="true">
        <div className="h-full bg-accent transition-[width] duration-75" style={{ width: `${Math.min(100, level * 600)}%` }} />
      </div>
      <div className="mt-2 flex items-center justify-between gap-3 text-[12px] text-muted">
        <span className="truncate">{current ? current.label : 'Opening the microphone'}</span>
        {devices.length > 1 && (
          <select
            value={current?.id || ''}
            onChange={(e) => onChange(e.target.value)}
            className="max-w-[140px] rounded border border-line bg-white px-1.5 py-0.5 text-[12px] text-ink outline-none focus:border-accent"
            aria-label="Microphone"
          >
            {devices.map((d) => <option key={d.deviceId} value={d.deviceId}>{d.label || 'Microphone'}</option>)}
          </select>
        )}
      </div>
      {input && (
        <p className="mt-1 text-[11.5px] text-faint">
          The line hears level {input.level.toFixed(3)}, speech score {input.speech_score.toFixed(2)} of 0.50 needed; {input.speech} speech {input.speech === 1 ? 'start' : 'starts'}, {input.turns} {input.turns === 1 ? 'turn' : 'turns'}, {input.ignored} set aside.
        </p>
      )}
      {hint && <p className="mt-1 border-l-2 border-accent pl-2 text-[12px] text-ink">{hint}</p>}
    </div>
  )
}

function useLevel(analyser) {
  const [level, setLevel] = useState(0)
  useEffect(() => {
    if (!analyser) return undefined
    const data = new Float32Array(analyser.fftSize)
    let frame
    let last = 0
    const tick = (time) => {
      if (time - last > 60) {
        analyser.getFloatTimeDomainData(data)
        let sum = 0
        for (let i = 0; i < data.length; i++) sum += data[i] * data[i]
        setLevel(Math.sqrt(sum / data.length))
        last = time
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [analyser])
  return level
}

// A round call control with its name under it, as phones draw them. Hanging
// up is the one red thing on the screen: it ends the call.
function Control({ label, onClick, pressed, tone, children }) {
  const look = tone === 'end'
    ? 'h-14 w-14 bg-danger text-white hover:bg-[#9a1f19]'
    : pressed
      ? 'h-12 w-12 bg-accent text-white'
      : 'h-12 w-12 border border-line text-ink hover:bg-hover'
  return (
    <div className="flex w-16 flex-col items-center gap-1.5">
      <button
        type="button"
        onClick={onClick}
        aria-label={label}
        aria-pressed={tone === 'end' ? undefined : Boolean(pressed)}
        className={`flex items-center justify-center rounded-full transition-colors ${look}`}
      >
        {children}
      </button>
      <span className="text-[11.5px] text-muted">{label}</span>
    </div>
  )
}

function Line({ item }) {
  if (item.who === 'note') return <p className="text-center text-[12px] text-faint">{item.text}</p>
  if (item.who === 'ignored') {
    return <p className="text-right text-[11.5px] text-faint">Heard "{item.text}", taken as {item.why?.startsWith('under') || item.why?.startsWith('listening') ? 'listening, not interrupting' : 'no turn'}.</p>
  }
  if (item.who === 'caller') {
    return (
      <div className="msg-enter flex justify-end">
        <p className="max-w-[80%] rounded-[16px] rounded-br-[3px] bg-bubble px-4 py-2.5 text-[14px] leading-[1.65] text-ink">{item.text}</p>
      </div>
    )
  }
  const heard = item.heard != null
  const rest = heard && item.text.startsWith(item.heard) ? item.text.slice(item.heard.length) : ''
  const m = item.metrics
  const notes = [
    item.superseded && 'Not said: you had already asked something else.',
    heard && 'You cut in; only what you heard is kept.',
    m?.ttfa_ms != null && `First audio ${secs(m.ttfa_ms)} after you stopped (answer ready in ${secs(m.ttft_ms)}).`,
    m?.kind === 'opening' && m?.agent_ms != null && `Greeting ready in ${secs(m.agent_ms)}.`,
  ].filter(Boolean)
  return (
    <div className="msg-enter max-w-[85%]">
      <p className={`text-[14px] leading-[1.65] ${item.superseded ? 'text-faint' : 'text-ink'}`}>
        {heard ? item.heard : item.text}
        {rest && <span className="text-faint">{rest}</span>}
      </p>
      {notes.length > 0 && <p className="mt-1 text-[11.5px] text-faint">{notes.join(' ')}</p>}
    </div>
  )
}

function secs(ms) {
  return ms == null ? '?' : `${(ms / 1000).toFixed(1)} s`
}

function clock(total) {
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

function formatPhone(phone) {
  const digits = String(phone || '')
  return digits.length === 10 ? `${digits.slice(0, 4)} ${digits.slice(4, 7)} ${digits.slice(7)}` : digits
}
