// The caller's side of a simulated phone call: microphone up, answers down.
//
// Everything that decides anything runs on the server (backend/src/api/voice.py):
// when the caller has finished, what they said, what the shop answers, and
// whether speech over the answer is an interruption. This file captures,
// plays, and reports back what only the browser knows: when playback started
// (the end-to-end timing the organisers ask to keep apart) and how much of an
// interrupted answer was heard.
//
// The audio path is backend/lab/voice/static/app.js's, where it was proven:
// ONE audio context for the microphone and the answers, answers played into
// its destination. That is what lets the browser's echo canceller take the
// answer out of the microphone. Playing through a second context was tried on
// 2026-09-27 and the assistant heard its own voice as the customer's.
//
// Two more things learned the hard way:
//
// - The context is created in the click that places the call (prepare).
//   Safari starts a context created later suspended, and the answer is silent.
// - The page owns the call, not the component that draws it. React's
//   StrictMode mounts a component twice in development; a call started and
//   stopped by the component died half-built ("null is not an object").
//
// Pausing an answer (the server's "pause", while it decides whether the
// caller really cut in) cannot suspend the context, which would stop the
// microphone too. Instead the queued pieces are stopped and their position
// kept; "resume" plays them again from exactly there, "stop" drops them.

import { getAccessToken } from './tokenStore'

const BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

function socketUrl(callId) {
  const origin = BASE || window.location.origin
  return `${origin.replace(/^http/, 'ws')}/api/calls/${callId}/voice`
}

export class VoiceCall {
  constructor() {
    this.on = () => {}
    this.ws = null
    this.ctx = null
    this.stream = null
    this.source = null
    this.capture = null
    this.micAnalyser = null
    this.agentAnalyser = null
    this.playing = null
    this.decodeChain = Promise.resolve()
    this.cancelled = new Set()
    this.started = false
    this.closed = false
    // Audio goes up only once the server has its models loaded: sound sent
    // earlier would queue and arrive late, all at once, with the wrong timing.
    this.ready = false
  }

  // Call inside the click that places the call, before anything is awaited.
  prepare() {
    const Context = window.AudioContext || window.webkitAudioContext
    this.ctx = new Context()
    this.ctx.resume()
    // Answers go through this to the speakers, so the bars can follow them.
    this.agentAnalyser = this.ctx.createAnalyser()
    this.agentAnalyser.fftSize = 2048
    this.agentAnalyser.connect(this.ctx.destination)
    return this
  }

  // Idempotent: a second call only replaces the listener.
  async connect(callId, on) {
    this.on = on
    if (this.started || this.closed) return
    this.started = true
    if (!this.ctx) this.prepare()
    await this.ctx.audioWorklet.addModule('/capture.js')
    if (this.closed) return
    this.capture = new AudioWorkletNode(this.ctx, 'capture')
    this.micAnalyser = this.ctx.createAnalyser()
    this.micAnalyser.fftSize = 2048
    const mute = this.ctx.createGain()
    mute.gain.value = 0
    // The worklet runs only when the graph pulls it; a silent path to the
    // speakers does that without playing the microphone back.
    this.capture.connect(mute).connect(this.ctx.destination)
    await this.useMicrophone(null)
    if (this.closed) return

    this.ws = new WebSocket(socketUrl(callId))
    this.ws.binaryType = 'arraybuffer'
    this.ws.onopen = () => this.send({ type: 'hello', token: getAccessToken(), sample_rate: this.ctx.sampleRate })
    this.ws.onmessage = (event) => this.handle(JSON.parse(event.data))
    this.ws.onclose = () => {
      this.stop()
      this.on({ type: 'closed' })
    }
    this.capture.port.onmessage = (event) => {
      if (this.ready && this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(event.data.buffer)
    }
  }

  // Open a microphone: the system's default input when deviceId is null
  // (System Settings > Sound > Input on a Mac), else the one chosen. The
  // browser's echo cancellation, noise suppression and gain control stay on.
  async useMicrophone(deviceId) {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
    })
    if (this.closed) {
      stream.getTracks().forEach((track) => track.stop())
      return
    }
    this.source?.disconnect()
    this.stream?.getTracks().forEach((track) => track.stop())
    this.stream = stream
    this.source = this.ctx.createMediaStreamSource(stream)
    this.source.connect(this.micAnalyser)
    this.source.connect(this.capture)
  }

  // The microphone in use, as the system names it.
  microphone() {
    const track = this.stream?.getAudioTracks()[0]
    return track ? { id: track.getSettings().deviceId, label: track.label || 'Microphone' } : null
  }

  async microphones() {
    const devices = await navigator.mediaDevices.enumerateDevices()
    return devices.filter((d) => d.kind === 'audioinput' && d.deviceId !== 'default')
  }

  setMuted(muted) {
    this.stream?.getAudioTracks().forEach((track) => {
      track.enabled = !muted
    })
  }

  hangUp() {
    this.send({ type: 'hangup' })
    const ws = this.ws
    setTimeout(() => ws?.close(), 300)
    this.stop()
  }

  stop() {
    if (this.closed) return
    this.closed = true
    this.stopPlayback()
    this.stream?.getTracks().forEach((track) => track.stop())
    if (this.ctx && this.ctx.state !== 'closed') this.ctx.close()
  }

  send(payload) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(payload))
  }

  handle(message) {
    switch (message.type) {
      case 'audio':
        this.decodeChain = this.decodeChain.then(() => this.enqueue(message)).catch(() => {})
        return
      case 'audio_end':
        this.decodeChain = this.decodeChain.then(() => this.finish(message))
        return
      case 'status':
        this.ready = true
        break
      case 'pause':
        this.pause(message.turn)
        break
      case 'resume':
        this.resume(message.turn)
        break
      case 'stop':
        this.interrupt(message.turn)
        break
      default:
        break
    }
    this.on(message)
  }

  // ── playback ──────────────────────────────────────────────────────────

  async enqueue(m) {
    if (!this.ctx || this.closed || this.cancelled.has(m.turn)) return
    const bytes = Uint8Array.from(atob(m.data), (c) => c.charCodeAt(0))
    const buffer = await this.ctx.decodeAudioData(bytes.buffer)
    if (this.closed || this.cancelled.has(m.turn)) return
    if (!this.playing || this.playing.turn !== m.turn) {
      this.stopPlayback()
      this.playing = { turn: m.turn, items: [], queueEnd: this.ctx.currentTime, started: false, stopped: false, pausedAt: null, lastSeq: null }
    }
    const playing = this.playing
    const at = playing.pausedAt != null ? playing.queueEnd : Math.max(this.ctx.currentTime + 0.02, playing.queueEnd)
    const item = { seq: m.seq, buffer, start: at, duration: buffer.duration, source: null }
    playing.items.push(item)
    playing.queueEnd = at + buffer.duration
    // While paused the piece waits in the queue; resume schedules it.
    if (playing.pausedAt == null) this.schedule(playing, item, at, 0)
    if (!playing.started && playing.pausedAt == null) {
      playing.started = true
      const delay = Math.max(0, (at - this.ctx.currentTime) * 1000)
      setTimeout(() => this.send({ type: 'playback_started', turn: m.turn }), delay)
    }
  }

  schedule(playing, item, when, offset) {
    const source = this.ctx.createBufferSource()
    source.buffer = item.buffer
    source.connect(this.agentAnalyser)
    source.start(when, offset)
    item.source = source
    source.onended = () => {
      if (this.playing === playing && !playing.stopped && playing.pausedAt == null && playing.lastSeq === item.seq && item.source === source) {
        this.send({ type: 'playback_ended', turn: playing.turn })
      }
    }
  }

  // The last piece is known only once synthesis is over; if playback has
  // already run past it, report the end now.
  finish(m) {
    if (!this.playing || this.playing.turn !== m.turn || !this.ctx) return
    this.playing.lastSeq = m.last_seq
    const item = this.playing.items.find((it) => it.seq === m.last_seq)
    if (item && this.playing.pausedAt == null && this.ctx.currentTime >= item.start + item.duration) {
      this.send({ type: 'playback_ended', turn: m.turn })
    }
  }

  pause(turn) {
    const playing = this.playing
    if (!playing || playing.turn !== turn || playing.pausedAt != null) return
    playing.pausedAt = this.ctx.currentTime
    for (const item of playing.items) this.silence(item)
  }

  resume(turn) {
    const playing = this.playing
    if (!playing || playing.turn !== turn || playing.pausedAt == null) return
    const pausedAt = playing.pausedAt
    const now = this.ctx.currentTime + 0.02
    const shift = now - pausedAt
    playing.pausedAt = null
    for (const item of playing.items) {
      const end = item.start + item.duration
      if (end <= pausedAt) continue
      const offset = Math.max(0, pausedAt - item.start)
      const when = item.start >= pausedAt ? item.start + shift : now
      item.start += shift
      this.schedule(playing, item, when, offset)
    }
    playing.queueEnd += shift
    if (!playing.started) {
      playing.started = true
      this.send({ type: 'playback_started', turn })
    }
  }

  interrupt(turn) {
    this.cancelled.add(turn)
    const playing = this.playing
    if (!playing || playing.turn !== turn || !this.ctx) return
    // Paused, the answer stands where the caller cut in.
    const now = playing.pausedAt ?? this.ctx.currentTime
    const items = playing.items
    const current =
      items.find((it) => now >= it.start && now < it.start + it.duration) ||
      items.find((it) => now < it.start) ||
      items[items.length - 1]
    const played = current ? Math.max(0, (now - current.start) * 1000) : 0
    this.stopPlayback()
    this.send({
      type: 'playback_stopped',
      turn,
      seq: current ? current.seq : 0,
      played_ms: played,
      duration_ms: current ? current.duration * 1000 : 1,
    })
  }

  silence(item) {
    try {
      item.source?.stop()
    } catch {
      // Not started yet, or already ended.
    }
    item.source = null
  }

  stopPlayback() {
    if (!this.playing) return
    this.playing.stopped = true
    for (const item of this.playing.items) this.silence(item)
    this.playing = null
  }
}
