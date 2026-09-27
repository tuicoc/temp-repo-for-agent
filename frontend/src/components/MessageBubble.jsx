// One turn of a conversation, drawn from a point of view.
//
// The viewer's own side sits on the right. On the customer's screen that is
// the customer, in a grey bubble with its lower corner squared off, and the
// assistant answers on the left as plain text under its name: a bubble reads
// as a remark, unbounded text reads as an answer. On a staff screen the
// customer is the other party, so they move to the left, and the assistant
// or consultant speaks from the right.

const SYSTEM_LABELS = {
  '[call connected]': 'Session started',
  '[consultant joined]': 'A consultant joined the conversation',
}

export function MessageBubble({ turn, perspective = 'customer', showMeta = false }) {
  const speaker = turn.speaker
  const meta = turn.meta || {}

  if (speaker === 'system') {
    // Each system mark has its own words; an unknown one shows nothing
    // rather than the wrong sentence.
    const label = SYSTEM_LABELS[turn.content]
    if (!label) return null
    return (
      <div className="flex justify-center">
        <span className="text-[11.5px] text-faint">{label}</span>
      </div>
    )
  }

  const isCustomer = speaker === 'customer'
  const isHuman = speaker === 'human_agent'
  const onRight = perspective === 'customer' ? isCustomer : !isCustomer
  const name = isCustomer ? 'Customer' : isHuman ? 'Consultant' : 'Assistant'

  const avatar = isCustomer ? (
    <div className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full border border-line bg-white">
      <span className="text-[10px] font-semibold text-muted">K</span>
    </div>
  ) : (
    <div className={`mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full ${isHuman ? 'border border-accent bg-white' : 'bg-accent'}`}>
      <span className={`text-[10px] font-semibold ${isHuman ? 'text-accent' : 'text-white'}`}>{isHuman ? 'C' : 'A'}</span>
    </div>
  )

  const showName = perspective === 'staff' || !isCustomer

  return (
    <div className={`msg-enter flex gap-3 ${onRight ? 'justify-end' : 'justify-start'}`}>
      {!onRight && avatar}

      <div className={`flex max-w-[80%] flex-col gap-1 ${onRight ? 'items-end' : 'items-start'}`}>
        {showName && (
          <div className={`mt-0.5 flex flex-wrap items-baseline gap-x-2 text-[12px] leading-snug text-muted ${onRight ? 'flex-row-reverse' : ''}`}>
            <span className="font-medium text-ink">{name}</span>
            {showMeta && meta.model && <span className="text-faint">{meta.model}</span>}
            {meta.confidence === 'low' && <span className="text-faint">low confidence</span>}
            {showMeta && meta.tool_calls?.length > 0 && (
              <span className="text-accent">
                {meta.tool_calls.length} tool {meta.tool_calls.length === 1 ? 'call' : 'calls'}
              </span>
            )}
            {meta.replayed && <span className="text-faint">replayed</span>}
          </div>
        )}

        <div
          className={`text-[14px] leading-[1.65] text-ink ${
            isCustomer ? `rounded-[16px] bg-bubble px-4 py-2.5 ${onRight ? 'rounded-br-[3px]' : 'rounded-bl-[3px]'}` : onRight ? 'text-right' : ''
          }`}
        >
          <p className="whitespace-pre-wrap">{turn.content}</p>
        </div>
      </div>

      {onRight && perspective === 'staff' && avatar}
    </div>
  )
}
