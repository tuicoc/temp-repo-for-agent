// One turn in the conversation.
//
// The assistant's confidence is shown when it is low. docs/flow.md section 10
// treats a low-confidence reply as the late signal that a question fell
// outside what the agent knows, so surfacing it is the difference between a
// customer being misled and a customer being told to ask someone else.

export function MessageBubble({ message }) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[80%] ${isUser ? 'text-right' : 'text-left'}`}>
        <div
          className={`inline-block whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-[14px] leading-6 ${
            isUser
              ? 'bg-app-accent text-white'
              : 'border border-app-border bg-app-surface text-app-dark'
          }`}
        >
          {message.content}
        </div>

        {!isUser && (message.model || message.confidence === 'low') && (
          <div className="mt-1 flex items-center gap-2 px-1 text-[11px] text-app-muted">
            {message.model && <span>{message.model}</span>}
            {message.confidence === 'low' && (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-amber-800">
                low confidence
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
