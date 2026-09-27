// The composer: what the customer types. Speaking to the shop is the hotline
// channel, chosen before the conversation starts (docs/design.md section
// 4.11); a spoken turn reaches the same assistant through the same harness.

import { useEffect, useRef, useState } from 'react'
import { ArrowUp } from 'lucide-react'

export function ChatInput({ onSend, busy, placeholder = 'Say something…' }) {
  const [text, setText] = useState('')
  const textarea = useRef(null)

  // Grow with the text, up to a point, so a long message is visible without
  // turning the composer into the whole page.
  useEffect(() => {
    const element = textarea.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 200)}px`
  }, [text])

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

  return (
    <div className="flex-shrink-0 px-4 pb-5 pt-2">
      <div className="mx-auto max-w-[680px] rounded-2xl border border-line bg-surface focus-within:border-accent focus-within:shadow-input">
        <textarea
          ref={textarea}
          rows={1}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          disabled={busy}
          className="w-full resize-none bg-transparent px-4 pt-3.5 text-[14px] leading-6
                     text-ink outline-none placeholder:text-faint disabled:opacity-60"
        />

        <div className="flex items-center justify-end gap-1.5 px-3 pb-3 pt-1">
          <button
            type="button"
            onClick={submit}
            disabled={busy || !text.trim()}
            aria-label="Send"
            className="flex h-8 w-8 items-center justify-center rounded-full bg-accent text-white
                       transition-colors hover:bg-[#274d73] disabled:opacity-30"
          >
            <ArrowUp size={16} />
          </button>
        </div>
      </div>

      <p className="mx-auto mt-2 max-w-[680px] text-center text-[11.5px] text-faint">
        You are talking to an automated assistant. Prices are only valid when quoted from the catalogue.
      </p>
    </div>
  )
}
