// Bars that show who is talking on a call, and what the assistant is doing.
//
// Adapted from ElevenLabs UI's BarVisualizer (https://github.com/elevenlabs/ui,
// apps/www/registry/elevenlabs-ui/ui/bar-visualizer.tsx), MIT License,
// Copyright (c) 2025 Eleven Labs Inc. The state sequences (connecting sweeps,
// listening blinks the centre bar, thinking pulses it, speaking follows the
// audio) and the band analysis are theirs. Changed here: it reads an
// AnalyserNode the call already has instead of opening an audio context per
// stream, speaks JavaScript rather than TypeScript, and wears this app's
// palette: the accent while the assistant speaks, grey while the caller does.

import { memo, useEffect, useMemo, useRef, useState } from 'react'

const normalizeDb = (value) => {
  if (value === -Infinity) return 0
  const minDb = -100
  const maxDb = -10
  const db = 1 - (Math.max(minDb, Math.min(maxDb, value)) * -1) / 100
  return Math.sqrt(db)
}

// Volume in `bands` frequency bands of the voice range, from an analyser.
function useMultibandVolume(analyser, bands, { loPass = 100, hiPass = 200, interval = 32 } = {}) {
  const [levels, setLevels] = useState(() => new Array(bands).fill(0))
  const current = useRef(levels)

  useEffect(() => {
    if (!analyser) {
      const empty = new Array(bands).fill(0)
      current.current = empty
      setLevels(empty)
      return undefined
    }
    const data = new Float32Array(analyser.frequencyBinCount)
    const chunk = Math.ceil((hiPass - loPass) / bands)
    let frame
    let last = 0
    const tick = (time) => {
      if (time - last >= interval) {
        analyser.getFloatFrequencyData(data)
        const next = new Array(bands)
        for (let i = 0; i < bands; i++) {
          let sum = 0
          let count = 0
          const end = Math.min(loPass + (i + 1) * chunk, hiPass)
          for (let j = loPass + i * chunk; j < end; j++) {
            sum += normalizeDb(data[j])
            count++
          }
          next[i] = count ? sum / count : 0
        }
        if (next.some((v, i) => Math.abs(v - current.current[i]) > 0.01)) {
          current.current = next
          setLevels(next)
        }
        last = time
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [analyser, bands, loPass, hiPass, interval])

  return levels
}

function sequenceFor(state, columns) {
  if (state === 'thinking' || state === 'listening') {
    return [[Math.floor(columns / 2)], [-1]]
  }
  if (state === 'connecting' || state === 'initializing') {
    return Array.from({ length: columns }, (_, x) => [x, columns - 1 - x])
  }
  return [Array.from({ length: columns }, (_, i) => i)]
}

function useBarAnimator(state, columns, interval) {
  const sequence = useMemo(() => sequenceFor(state, columns), [state, columns])
  const [frame, setFrame] = useState(sequence[0])
  useEffect(() => {
    let index = 0
    let start = performance.now()
    let id
    setFrame(sequence[0])
    const animate = (time) => {
      if (time - start >= interval) {
        index = (index + 1) % sequence.length
        setFrame(sequence[index])
        start = time
      }
      id = requestAnimationFrame(animate)
    }
    id = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(id)
  }, [sequence, interval])
  return frame
}

// state: connecting | initializing | listening | thinking | speaking.
// tone: "agent" (accent) or "caller" (grey), for whose voice the bars follow.
export const BarVisualizer = memo(function BarVisualizer({ state, analyser, tone = 'agent', barCount = 7, className = '' }) {
  const levels = useMultibandVolume(analyser, barCount)
  const highlighted = useBarAnimator(
    state,
    barCount,
    state === 'connecting' || state === 'initializing' ? 2000 / barCount : state === 'thinking' ? 150 : state === 'listening' ? 500 : 1000,
  )
  const live = state === 'speaking'
  const fill = tone === 'agent' ? 'bg-accent' : 'bg-muted'

  return (
    <div className={`flex items-center justify-center gap-2 ${className}`} data-state={state} aria-hidden="true">
      {levels.map((level, index) => {
        const height = Math.min(100, Math.max(14, level * 100 + 5))
        const on = live || highlighted?.includes(index)
        return (
          <div
            key={index}
            className={`w-[10px] rounded-full transition-all duration-150 ${on ? fill : 'bg-line-2'} ${state === 'thinking' && on ? 'animate-pulse' : ''}`}
            style={{ height: `${live ? height : 14}%` }}
          />
        )
      })}
    </div>
  )
})
