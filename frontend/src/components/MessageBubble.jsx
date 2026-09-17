// One turn in the conversation.
//
// Shaped after the reference project: the customer gets a grey bubble on the
// right with its lower corner squared off, and the assistant gets no bubble at
// all — just text, left-aligned under its name. That asymmetry is deliberate.
// A bubble reads as a remark; unbounded text reads as an answer, which is what
// a long reply with a price in it should look like.

const AVATAR = 'linear-gradient(135deg, #E07840 0%, #C04898 100%)'

export function MessageBubble({ message }) {
  const isUser = message.role === 'user'

  return (
    <div className={`msg-enter flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div
          className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full shadow-sm"
          style={{ background: AVATAR }}
        >
          <span className="text-[10px] font-semibold text-white">A</span>
        </div>
      )}

      <div className={`flex flex-col gap-2 ${isUser ? 'max-w-[75%] items-end' : 'max-w-[85%] items-start'}`}>
        {!isUser && (
          <div className="mt-0.5 flex flex-wrap items-baseline gap-x-1.5 text-[11px] font-medium leading-snug text-muted">
            <span>Assistant</span>
            {message.model && <span className="font-normal text-faint">· {message.model}</span>}
            {message.confidence === 'low' && (
              <span className="rounded-full bg-amber-50 px-1.5 py-px font-normal text-amber-700">
                low confidence
              </span>
            )}
          </div>
        )}

        <div
          className={`text-[14px] leading-[1.65] ${
            isUser
              ? 'rounded-[18px] rounded-br-[4px] bg-bubble px-4 py-2.5 text-ink'
              : 'px-0 py-0 text-ink'
          }`}
        >
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
      </div>

      {isUser && (
        <div className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-muted shadow-sm">
          <span className="text-[10px] font-semibold text-white">U</span>
        </div>
      )}
    </div>
  )
}
