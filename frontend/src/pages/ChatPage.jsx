// The chat screen: a list of conversations, the current one, and the composer.
//
// A turn is sent over SSE. The backend answers with a filler frame straight
// away, then the finished reply — not a token stream, because docs/flow.md
// section 8.4 requires the guardrail to see a complete sentence before the
// customer does. The typing indicator below is therefore honest: something is
// happening, and nothing is being shown that has not been checked.

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, sendMessage } from '../services/api'
import { useAuth } from '../context/AuthContext'
import { ChatInput } from '../components/ChatInput'
import { MessageBubble } from '../components/MessageBubble'
import { Sidebar } from '../components/Sidebar'

export function ChatPage() {
  const { user, logout } = useAuth()
  const [conversations, setConversations] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])
  const [models, setModels] = useState([])
  const [model, setModel] = useState(null)
  const [pending, setPending] = useState(null)
  const [error, setError] = useState('')
  const bottom = useRef(null)

  useEffect(() => {
    api.models().then((list) => {
      setModels(list)
      setModel(list[0] ?? null)
    }).catch(() => setError('Could not load the model list.'))
    refreshConversations()
  }, [])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, pending])

  const refreshConversations = useCallback(async () => {
    try {
      const list = await api.conversations()
      setConversations(list)
      setActiveId((current) => current ?? list[0]?.id ?? null)
    } catch {
      setError('Could not load your conversations.')
    }
  }, [])

  useEffect(() => {
    if (activeId == null) {
      setMessages([])
      return
    }
    api.messages(activeId).then(setMessages).catch(() => setError('Could not load this conversation.'))
  }, [activeId])

  async function handleCreate() {
    const conversation = await api.createConversation()
    setConversations((list) => [conversation, ...list])
    setActiveId(conversation.id)
    setMessages([])
  }

  async function handleDelete(id) {
    await api.deleteConversation(id)
    setConversations((list) => list.filter((c) => c.id !== id))
    if (id === activeId) setActiveId(null)
  }

  async function handleSend(content) {
    setError('')
    let conversationId = activeId

    // Typing before picking a conversation should just work.
    if (conversationId == null) {
      const conversation = await api.createConversation()
      setConversations((list) => [conversation, ...list])
      setActiveId(conversation.id)
      conversationId = conversation.id
    }

    setMessages((list) => [...list, { id: `local-${Date.now()}`, role: 'user', content }])
    setPending({ filler: '' })

    try {
      await sendMessage(
        conversationId,
        { content, provider: model?.provider, model: model?.id },
        {
          filler: (data) => setPending({ filler: data.text }),
          message: (data) =>
            setMessages((list) => [
              ...list,
              {
                id: `reply-${Date.now()}`,
                role: 'assistant',
                content: data.content,
                model: data.model,
                confidence: data.confidence,
              },
            ]),
          error: (data) => setError(data.message),
        },
      )
      refreshConversations()
    } catch (err) {
      setError(err.message || 'The agent could not be reached.')
    } finally {
      setPending(null)
    }
  }

  return (
    <div className="flex h-full">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={setActiveId}
        onCreate={handleCreate}
        onDelete={handleDelete}
        email={user.email}
        onLogout={logout}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-3xl space-y-4 px-4 py-6">
            {messages.length === 0 && !pending && (
              <div className="pt-24 text-center">
                <h2 className="text-[20px] font-semibold text-app-dark">How can we help?</h2>
                <p className="mt-2 text-[13px] text-app-muted">
                  Ask about a product and the assistant will answer in Vietnamese.
                </p>
              </div>
            )}

            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}

            {pending && (
              <div className="flex justify-start">
                <div className="inline-flex items-center gap-2 rounded-2xl border border-app-border
                                bg-app-surface px-4 py-2.5 text-[14px] text-app-muted">
                  <span className="flex gap-1">
                    <Dot delay="0ms" />
                    <Dot delay="150ms" />
                    <Dot delay="300ms" />
                  </span>
                  {pending.filler}
                </div>
              </div>
            )}

            {error && (
              <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-[12px] text-red-700">
                {error}
              </p>
            )}

            <div ref={bottom} />
          </div>
        </div>

        <ChatInput
          models={models}
          model={model?.id}
          onModelChange={setModel}
          onSend={handleSend}
          busy={Boolean(pending)}
        />
      </main>
    </div>
  )
}

function Dot({ delay }) {
  return (
    <span
      className="h-1.5 w-1.5 animate-bounce rounded-full bg-app-muted/60"
      style={{ animationDelay: delay }}
    />
  )
}
