// Past conversations, and the way out. 260px on a light grey ground, as in the
// reference project — enough separation from the white transcript to read as a
// different surface without drawing a line under it.

import { LogOut, MessageSquarePlus, Trash2 } from 'lucide-react'

export function Sidebar({ conversations, activeId, onSelect, onCreate, onDelete, email, onLogout }) {
  return (
    <aside className="flex w-[260px] flex-shrink-0 flex-col bg-sidebar">
      <div className="p-3">
        <button
          type="button"
          onClick={onCreate}
          className="flex w-full items-center gap-2 rounded-xl border border-line bg-surface px-3 py-2
                     text-[13px] text-ink shadow-sm transition-colors hover:bg-hover"
        >
          <MessageSquarePlus size={15} className="text-muted" />
          New conversation
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-2">
        {conversations.length === 0 && (
          <p className="px-3 py-2 text-[12.5px] text-faint">No conversations yet.</p>
        )}
        {conversations.map((conversation) => (
          <div
            key={conversation.id}
            className={`group mb-0.5 flex items-center rounded-lg transition-colors ${
              conversation.id === activeId ? 'bg-[#E6E6E6]' : 'hover:bg-[#EAEAEA]'
            }`}
          >
            <button
              type="button"
              onClick={() => onSelect(conversation.id)}
              className="flex-1 truncate px-3 py-2 text-left text-[13px] text-ink"
            >
              {conversation.title}
            </button>
            <button
              type="button"
              onClick={() => onDelete(conversation.id)}
              aria-label={`Delete ${conversation.title}`}
              className="mr-1.5 rounded p-1 text-faint opacity-0 transition hover:text-red-600
                         focus:opacity-100 group-hover:opacity-100"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </nav>

      <div className="border-t border-[#E3E3E3] p-3">
        <div className="mb-1.5 truncate px-1 text-[12px] text-faint">{email}</div>
        <button
          type="button"
          onClick={onLogout}
          className="flex w-full items-center gap-2 rounded-lg px-1 py-1.5 text-[13px]
                     text-muted transition-colors hover:text-accent"
        >
          <LogOut size={15} />
          Sign out
        </button>
      </div>
    </aside>
  )
}
