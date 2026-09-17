// The composer: what to say, which model says it back, and a microphone that
// does nothing yet.
//
// The microphone is deliberately present and deliberately disabled. Real-time
// voice is out of scope for M1 — docs/flow.md Appendix A lists it among the
// things with no feature flag, and the brief's first way to lose marks is
// spending weeks on it. Showing the affordance greyed out says where it will
// go without pretending it is there.

import { useEffect, useRef, useState } from 'react'
import { ArrowUp, ChevronDown, Mic } from 'lucide-react'

export function ChatInput({ models, model, onModelChange, onSend, busy }) {
  const [text, setText] = useState('')
  const [pickerOpen, setPickerOpen] = useState(false)
  const textarea = useRef(null)
  const picker = useRef(null)

  // Grow with the text, up to a point, so a long message is visible without
  // turning the composer into the whole page.
  useEffect(() => {
    const element = textarea.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 200)}px`
  }, [text])

  useEffect(() => {
    if (!pickerOpen) return
    const close = (event) => {
      if (!picker.current?.contains(event.target)) setPickerOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [pickerOpen])

  function submit() {
    const value = text.trim()
    if (!value || busy) return
    setText('')
    onSend(value)
  }

  function onKeyDown(event) {
    // Enter sends, Shift+Enter makes a new line — what every chat does.
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  const selected = models.find((m) => m.id === model)

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-6">
      <div className="rounded-2xl border border-app-border bg-app-surface shadow-sm">
        <textarea
          ref={textarea}
          rows={1}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask about a product, a price, or an order…"
          className="w-full resize-none bg-transparent px-4 pt-3.5 text-[14px] leading-6
                     text-app-dark outline-none placeholder:text-app-muted/70"
        />

        <div className="flex items-center justify-between gap-2 px-3 pb-3 pt-1">
          <div className="relative" ref={picker}>
            <button
              type="button"
              onClick={() => setPickerOpen((open) => !open)}
              aria-expanded={pickerOpen}
              className="flex items-center gap-1.5 rounded-full border border-app-border bg-white
                         px-3 py-1.5 text-[12px] text-app-body transition hover:bg-app-bg"
            >
              <span className="max-w-[220px] truncate">{selected?.label ?? 'Select a model'}</span>
              <ChevronDown size={13} />
            </button>

            {pickerOpen && (
              <div
                role="listbox"
                className="absolute bottom-full left-0 z-10 mb-2 max-h-64 w-[320px] overflow-y-auto
                           rounded-xl border border-app-border bg-app-surface p-1 shadow-lg"
              >
                {models.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    role="option"
                    aria-selected={option.id === model}
                    onClick={() => {
                      onModelChange(option)
                      setPickerOpen(false)
                    }}
                    className={`block w-full truncate rounded-lg px-3 py-2 text-left text-[12px] transition
                                hover:bg-app-bg ${
                                  option.id === model ? 'bg-app-accent-dim text-app-dark' : 'text-app-body'
                                }`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="flex items-center gap-1.5">
            <button
              type="button"
              disabled
              title="Voice is not available yet"
              aria-label="Voice input, not available yet"
              className="flex h-8 w-8 items-center justify-center rounded-full text-app-muted/50
                         transition disabled:cursor-not-allowed"
            >
              <Mic size={16} />
            </button>

            <button
              type="button"
              onClick={submit}
              disabled={busy || !text.trim()}
              aria-label="Send"
              className="flex h-8 w-8 items-center justify-center rounded-full bg-app-accent text-white
                         transition hover:brightness-95 disabled:opacity-40"
            >
              <ArrowUp size={16} />
            </button>
          </div>
        </div>
      </div>

      <p className="mt-2 text-center text-[11px] text-app-muted">
        Replies come from an automated assistant and may be wrong. Prices are only
        valid when quoted from the catalogue.
      </p>
    </div>
  )
}
