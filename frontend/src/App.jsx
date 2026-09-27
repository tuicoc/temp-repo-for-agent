// Screens, by who is signed in. A customer account gets the chat and nothing
// else, full width, the way a visitor to the shop's site would. A staff
// account gets the sidebar with every screen, the chat included, so a tester
// can play both sides from two browser profiles.
//
// Routes are URL hashes so a demo opens two windows from one origin without
// a router dependency. Every screen sits behind a sign-in so that a public
// URL is not a free LLM bill.

import { useEffect, useState } from 'react'
import { LogOut } from 'lucide-react'
import { useAuth } from './context/AuthContext'
import { Shell, NAV } from './components/Shell'
import { LoginPage } from './pages/LoginPage'
import { ChatPage } from './pages/ChatPage'
import { ConsolePage } from './pages/ConsolePage'
import { HandoverPage } from './pages/HandoverPage'
import { QaPage } from './pages/QaPage'
import { RunsPage } from './pages/RunsPage'
import { DatasetPage } from './pages/DatasetPage'
import { ImprovePage } from './pages/ImprovePage'
import { KnowledgePage } from './pages/KnowledgePage'
import { AdminPage } from './pages/AdminPage'

const PAGES = {
  '#/console': ConsolePage,
  '#/handover': HandoverPage,
  '#/qa': QaPage,
  '#/runs': RunsPage,
  '#/dataset': DatasetPage,
  '#/improve': ImprovePage,
  '#/knowledge': KnowledgePage,
  '#/admin': AdminPage,
}

function useHashRoute(fallback) {
  const [hash, setHash] = useState(window.location.hash || fallback)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash || fallback)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [fallback])
  return hash
}

export default function App() {
  const { user, restoring, logout } = useAuth()
  const isStaff = user && user.role !== 'customer'
  const route = useHashRoute(isStaff ? '#/console' : '#/chat')

  if (restoring) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-line border-t-accent" />
      </div>
    )
  }

  if (!user) return <LoginPage />

  if (!isStaff) {
    return (
      <div className="flex h-full flex-col bg-surface">
        <div className="flex h-11 flex-shrink-0 items-center justify-between border-b border-line px-5">
          <span className="text-[13px] font-semibold text-ink">Agent Core</span>
          <button type="button" onClick={logout} className="flex items-center gap-1.5 text-[12px] text-muted transition-colors hover:text-ink">
            <LogOut size={13} />
            Sign out
          </button>
        </div>
        <div className="min-h-0 flex-1">
          <ChatPage />
        </div>
      </div>
    )
  }

  const known = NAV.flatMap((g) => g.items).find((item) => route.startsWith(item.hash))
  const hash = known?.hash ?? '#/console'
  const Current = PAGES[hash]

  return (
    <Shell route={hash} email={user.email} onLogout={logout}>
      <Current />
    </Shell>
  )
}
