// Past conversations, and the way out.

import { LogOut, MessageSquarePlus, Trash2 } from 'lucide-react'

export function Sidebar({ conversations, activeId, onSelect, onCreate, onDelete, email, onLogout }) {
  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-app-border bg-app-sidebar">
      <div className="p-3">
        <button
          type="button"
          onClick={onCreate}
          className="flex w-full items-center gap-2 rounded-xl border border-app-border bg-app-surface
                     px-3 py-2 text-[13px] text-app-body transition hover:bg-white"
        >
          <MessageSquarePlus size={15} />
          New conversation
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-2">
        {conversations.length === 0 && (
          <p className="px-3 py-2 text-[12px] text-app-muted">No conversations yet.</p>
        )}
        {conversations.map((conversation) => (
          <div
            key={conversation.id}
            className={`group flex items-center gap-1 rounded-lg px-1 ${
              conversation.id === activeId ? 'bg-app-accent-dim' : 'hover:bg-app-bg'
            }`}
          >
            <button
              type="button"
              onClick={() => onSelect(conversation.id)}
              className="flex-1 truncate px-2 py-2 text-left text-[13px] text-app-body"
            >
              {conversation.title}
            </button>
            <button
              type="button"
              onClick={() => onDelete(conversation.id)}
              aria-label={`Delete ${conversation.title}`}
              className="mr-1 rounded p-1 text-app-muted opacity-0 transition
                         hover:text-red-600 group-hover:opacity-100"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </nav>

      <div className="border-t border-app-border p-3">
        <div className="mb-2 truncate px-1 text-[12px] text-app-muted">{email}</div>
        <button
          type="button"
          onClick={onLogout}
          className="flex w-full items-center gap-2 rounded-lg px-1 py-1.5 text-[13px]
                     text-app-body transition hover:text-app-accent"
        >
          <LogOut size={15} />
          Sign out
        </button>
      </div>
    </aside>
  )
}
