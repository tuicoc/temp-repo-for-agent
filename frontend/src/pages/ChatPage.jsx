// The customer's side. Three ways to reach the shop, all simulated here and
// all going through the same assistant (docs/design.md sections 4.2, 4.11):
//
// - the shop's own chat on the website: anonymous until the visitor states a
//   phone number, then recognised after one confirming question;
// - a Zalo conversation: the Zalo account is known from the connection, so a
//   customer met before is recognised at once;
// - a call to the hotline: spoken, from a phone number, which is the caller id.
//
// A chat session survives leaving the page and coming back; it ends when the
// customer ends it, signs out, or half an hour passes in silence. A call ends
// when either side hangs up. "Talk to a person" hands a chat to a consultant.

import { useEffect, useRef, useState } from 'react'
import { api, sendTurn } from '../services/api'
import { clearSessionId, resumeSession, setSessionId } from '../services/session'
import { ChatInput } from '../components/ChatInput'
import { CallView } from '../components/CallView'
import { MessageBubble } from '../components/MessageBubble'
import { VoiceCall } from '../services/voice'
import { Button, Tag, inputClass } from '../components/ui'

const TIER_LABEL = {
  PROBABLE: 'Recognised, confirming',
  AMBIGUOUS: 'Shared number, confirming',
  VERIFIED: 'Recognised',
}

const CHANNELS = [
  {
    id: 'web',
    name: 'Chat on the website',
    detail: 'You start anonymous. Mention your phone number and the assistant picks up where you left off.',
    action: 'Start chat',
  },
  {
    id: 'zalo',
    name: 'Message on Zalo',
    detail: 'Your Zalo account tells the shop who you are, so a returning customer is recognised straight away.',
    field: { label: 'Your Zalo account', placeholder: 'zalo_hoa73', key: 'channel_id' },
    action: 'Open Zalo chat',
  },
  {
    id: 'hotline',
    name: 'Call the hotline',
    detail: 'A spoken call, answered aloud. Any number will do: it is the caller id the shop sees, so calling again from it picks up where you left off.',
    field: { label: 'Calling from', placeholder: 'Any number', key: 'phone', inputMode: 'tel' },
    action: 'Call',
  },
]

const POLL_MS = 3000

export function ChatPage() {
  const [session, setSession] = useState(null)
  const [turns, setTurns] = useState([])
  const [status, setStatus] = useState('checking')
  const [pending, setPending] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const [error, setError] = useState('')
  const [call, setCall] = useState(null)
  const bottom = useRef(null)
  const checked = useRef(false)
  // The call belongs to the page: created in the click that places it (Safari
  // plays nothing from an audio context made later), ended by hanging up or
  // by leaving the page.
  const phone = useRef(null)

  useEffect(() => () => phone.current?.stop(), [])

  useEffect(() => {
    // StrictMode mounts twice in development; one check is enough.
    if (checked.current) return
    checked.current = true
    resumeSession().then((existing) => {
      if (existing && existing.channel !== 'hotline') {
        setSession(existing)
        setTurns(existing.turns)
        setStatus('live')
      } else {
        setStatus('choose')
      }
    })
  }, [])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns, pending, waiting])

  // With a consultant on the line, replies arrive outside our own requests.
  const copilot = session?.mode === 'copilot'
  useEffect(() => {
    if (status !== 'live' || !copilot || session == null) return
    const timer = setInterval(() => refresh(session.id), POLL_MS)
    return () => clearInterval(timer)
  }, [status, copilot, session?.id])

  async function refresh(sessionId) {
    try {
      const fresh = await api.call(sessionId)
      setSession(fresh)
      setTurns(fresh.turns)
      const spoken = fresh.turns.filter((t) => t.speaker !== 'system')
      if (spoken[spoken.length - 1]?.speaker !== 'customer') setWaiting(false)
      if (fresh.ended_at) {
        clearSessionId()
        setStatus('ended')
      }
    } catch {
      // Try again on the next tick.
    }
  }

  async function begin(channel, value) {
    setError('')
    setTurns([])
    setWaiting(false)
    try {
      if (channel === 'hotline') {
        phone.current?.stop()
        phone.current = new VoiceCall().prepare()
        const created = await api.startCall({ channel, phone: value })
        setCall({ ...created, phone: value.replace(/\D/g, '') })
        setStatus('calling')
        return
      }
      setStatus('starting')
      const created = await api.startCall({ channel, ...(channel === 'zalo' ? { channel_id: value } : {}) })
      setSessionId(created.id)
      setSession(created)
      setStatus('live')
      await runTurn(created.id, null)
    } catch (err) {
      phone.current?.stop()
      phone.current = null
      setError(err.message || 'Could not reach the shop.')
      setStatus('choose')
    }
  }

  async function runTurn(sessionId, content) {
    const body = { turn_id: crypto.randomUUID(), ...(content != null ? { content } : {}) }
    let delivered = false
    const handlers = {
      message: (data) => {
        delivered = true
        setTurns((list) => [...list, { id: `a-${Date.now()}`, speaker: 'agent', content: data.content, meta: data.meta }])
      },
      waiting: () => {
        delivered = true
        setWaiting(true)
      },
      error: (data) => setError(data.message),
    }
    setPending(true)
    try {
      try {
        await sendTurn(sessionId, body, handlers)
      } catch (err) {
        // An HTTP error is final; a network failure gets one retry with the
        // same turn id, which the server replays rather than answering twice.
        if (delivered || err.status) throw err
        await new Promise((resolve) => setTimeout(resolve, 1000))
        await sendTurn(sessionId, body, handlers)
      }
    } finally {
      setPending(false)
    }
    // The server's transcript is the truth: it carries identity changes and,
    // in copilot mode, the consultant's words.
    await refresh(sessionId)
  }

  async function say(content) {
    setError('')
    setTurns((list) => [...list, { id: `c-${Date.now()}`, speaker: 'customer', content }])
    try {
      await runTurn(session.id, content)
    } catch (err) {
      if (err.status === 409 && /ended/i.test(err.message)) {
        clearSessionId()
        setStatus('ended')
        return
      }
      setError(err.message || 'The assistant could not be reached.')
    }
  }

  async function askForPerson() {
    setError('')
    try {
      await api.requestHandoff(session.id)
      await refresh(session.id)
    } catch (err) {
      setError(err.message || 'Could not reach a consultant.')
    }
  }

  async function end() {
    clearSessionId()
    try {
      setSession(await api.endCall(session.id))
    } catch (err) {
      setError(err.message || 'Could not end the chat.')
    }
    setStatus('ended')
  }

  if (status === 'checking') return null

  if (status === 'calling' && call) {
    return (
      <CallView
        call={call}
        line={phone.current}
        onBack={() => {
          phone.current?.stop()
          phone.current = null
          setCall(null)
          setStatus('choose')
        }}
      />
    )
  }

  if (status === 'choose') return <ChannelChoice onChoose={begin} error={error} />

  const tierLabel = session ? TIER_LABEL[session.tier] : null
  const handoff = session?.handoff_status
  const who = handoff === 'accepted' ? 'Consultant' : 'Assistant'
  const where = session?.channel === 'zalo' ? `Zalo, ${session.channel_ref}` : 'Website chat'
  const line =
    status === 'ended' ? 'Chat ended'
    : status === 'starting' ? 'Connecting'
    : handoff === 'pending' ? 'Connecting you to a consultant'
    : handoff === 'accepted' ? 'A consultant is with you'
    : where

  return (
    <div className="relative flex h-full flex-col bg-surface">
      <header className="flex h-14 flex-shrink-0 items-center justify-between border-b border-line px-6">
        <div className="flex items-center gap-3">
          <span className={`h-2 w-2 rounded-full ${status === 'live' ? 'bg-accent' : 'bg-line-2'}`} />
          <div>
            <div className="text-[14px] font-medium leading-tight text-ink">{who}</div>
            <div className="text-[12px] text-muted">
              {line}
              {tierLabel && (
                <Tag tone="accent" className="ml-2">
                  {tierLabel}{session.customer_label ? `, ${session.customer_label}` : session.phone_last4 ? `, number ending ${session.phone_last4}` : ''}
                </Tag>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {status === 'live' && !handoff && (
            <Button variant="ghost" onClick={askForPerson} disabled={pending} title={pending ? 'Wait for the assistant to finish' : undefined}>
              Talk to a person
            </Button>
          )}
          {status === 'live' ? (
            <Button onClick={end}>End chat</Button>
          ) : status === 'starting' ? null : (
            <Button variant="primary" onClick={() => setStatus('choose')}>New conversation</Button>
          )}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[680px] space-y-6 px-6 py-8">
          {turns.map((turn) => (
            <MessageBubble key={turn.id} turn={turn} />
          ))}

          {pending && (
            <div className="msg-enter flex justify-start gap-3">
              <div className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-accent">
                <span className="text-[10px] font-semibold text-white">A</span>
              </div>
              <span className="flex gap-1 pt-3" aria-label="The assistant is answering">
                <Dot delay="0ms" />
                <Dot delay="150ms" />
                <Dot delay="300ms" />
              </span>
            </div>
          )}

          {waiting && !pending && (
            <p className="text-[12.5px] text-faint">
              {handoff === 'accepted' ? 'The consultant is replying.' : 'Waiting for a consultant to pick this up.'}
            </p>
          )}

          {error && <p role="alert" className="border-l-2 border-danger pl-3 text-[13px] text-ink">{error}</p>}

          {status === 'ended' && (
            <p className="pt-2 text-center text-[12.5px] text-faint">
              This conversation has ended. The shop remembers it: start a new one the same way and pick up where you left off.
            </p>
          )}

          <div ref={bottom} />
        </div>
      </div>

      {status === 'live' && (
        <ChatInput onSend={say} busy={pending} placeholder={handoff ? 'Message the consultant' : 'Ask about a product, a price, or an order'} />
      )}
    </div>
  )
}

function ChannelChoice({ onChoose, error }) {
  const [chosen, setChosen] = useState('web')
  const [values, setValues] = useState(() => ({ zalo: '', hotline: randomNumber() }))
  const [busy, setBusy] = useState(false)

  async function go(channel) {
    const value = values[channel] ?? ''
    if (channel !== 'web' && !value.trim()) return
    setBusy(true)
    try {
      await onChoose(channel, value.trim())
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto bg-surface">
      <div className="mx-auto w-full max-w-[560px] px-6 py-14">
        <h1 className="text-[20px] font-semibold text-ink">Contact the shop</h1>
        <p className="mt-1.5 text-[13px] leading-relaxed text-muted">
          Air purifiers, water filters, fans, shoes, baby goods. Whichever way you get in touch, the same assistant answers and remembers you next time.
        </p>

        <ul className="mt-8 border-t border-line" role="radiogroup" aria-label="How to contact the shop">
          {CHANNELS.map((channel) => {
            const active = chosen === channel.id
            return (
              <li key={channel.id} className="relative border-b border-line">
                {active && <span className="absolute left-0 top-3 h-[calc(100%-24px)] w-0.5 rounded-full bg-accent" />}
                <button
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => setChosen(channel.id)}
                  className="w-full py-4 pl-5 pr-2 text-left"
                >
                  <span className={`block text-[14px] ${active ? 'font-medium text-ink' : 'text-ink'}`}>{channel.name}</span>
                  <span className="mt-0.5 block text-[12.5px] leading-relaxed text-muted">{channel.detail}</span>
                </button>
                {active && (
                  <form
                    className="flex items-end gap-2 pb-4 pl-5 pr-2"
                    onSubmit={(event) => {
                      event.preventDefault()
                      go(channel.id)
                    }}
                  >
                    {channel.field && (
                      <label className="block flex-1">
                        <span className="mb-1 block text-[12px] text-muted">{channel.field.label}</span>
                        <input
                          autoFocus
                          inputMode={channel.field.inputMode}
                          value={values[channel.id]}
                          onChange={(e) => setValues((v) => ({ ...v, [channel.id]: e.target.value }))}
                          placeholder={channel.field.placeholder}
                          className={inputClass}
                        />
                      </label>
                    )}
                    <Button variant="primary" type="submit" disabled={busy || (channel.field && !values[channel.id].trim())}>
                      {channel.action}
                    </Button>
                  </form>
                )}
                {active && channel.id === 'hotline' && isSafari() && (
                  <p className="-mt-1 mb-4 ml-5 mr-2 border-l-2 border-accent pl-3 text-[12.5px] leading-relaxed text-ink">
                    Calls work best in Chrome. Safari hands the microphone to macOS voice processing, which lets through
                    less of your voice, most of all while the assistant is speaking. Headphones help in either browser.
                  </p>
                )}
              </li>
            )
          })}
        </ul>

        {error && <p role="alert" className="mt-5 border-l-2 border-danger pl-3 text-[13px] text-ink">{error}</p>}
      </div>
    </div>
  )
}

function isSafari() {
  const agent = navigator.userAgent
  return /Safari/.test(agent) && !/Chrome|Chromium|CriOS|FxiOS|Edg/.test(agent)
}

// A made-up mobile number for a simulated call: 09 and eight random digits.
function randomNumber() {
  const digits = Array.from({ length: 8 }, () => Math.floor(Math.random() * 10)).join('')
  return `09${digits.slice(0, 2)} ${digits.slice(2, 5)} ${digits.slice(5)}`
}

function Dot({ delay }) {
  return <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-faint" style={{ animationDelay: delay }} />
}
