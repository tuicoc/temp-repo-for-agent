// The frame around every signed-in screen: a sidebar on the left with the
// screens grouped by who uses them, the screen itself on the right.
//
// The active item is marked with a rule on its left in the accent, the way
// a line in a ledger is pointed at, not with a filled pill. Groups are named
// by the work, not by the code behind it.

import { BarChart2, BookOpen, ClipboardList, Database, Headphones, ListChecks, LogOut, ArrowRightLeft, Settings } from 'lucide-react'

// The customer's chat is not here: staff see conversations from the console,
// and the customer account is the way to be a customer.
export const NAV = [
  {
    group: 'Operations',
    items: [
      { hash: '#/console', label: 'Console', icon: Headphones },
      { hash: '#/handover', label: 'Shift handover', icon: ArrowRightLeft },
    ],
  },
  {
    group: 'Quality',
    items: [
      { hash: '#/qa', label: 'QA review', icon: ClipboardList },
      { hash: '#/runs', label: 'Runs and metrics', icon: BarChart2 },
      { hash: '#/dataset', label: 'Dataset', icon: Database },
    ],
  },
  {
    group: 'Knowledge',
    items: [
      { hash: '#/improve', label: 'Improvement', icon: ListChecks },
      { hash: '#/knowledge', label: 'Knowledge and feedback', icon: BookOpen },
    ],
  },
  {
    group: 'System',
    items: [{ hash: '#/admin', label: 'Admin', icon: Settings }],
  },
]

export function Shell({ route, email, onLogout, children }) {
  return (
    <div className="flex h-full bg-surface">
      <aside className="flex w-[232px] flex-shrink-0 flex-col border-r border-line">
        <div className="px-5 pb-4 pt-5">
          <div className="text-[15px] font-semibold leading-none text-ink">Agent Core</div>
          <div className="mt-1 text-[12px] text-faint">Telesales assistant</div>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 pb-4">
          {NAV.map((section) => (
            <div key={section.group} className="mb-4">
              <div className="mb-1 px-2 text-[11.5px] font-medium text-faint">{section.group}</div>
              <ul>
                {section.items.map((item) => {
                  const active = route.startsWith(item.hash)
                  const Icon = item.icon
                  return (
                    <li key={item.hash}>
                      <a
                        href={item.hash}
                        aria-current={active ? 'page' : undefined}
                        className={`relative flex items-center gap-2.5 rounded-md py-1.5 pl-3 pr-2 text-[13px] transition-colors hover:bg-hover ${
                          active ? 'font-medium text-ink' : 'text-muted hover:text-ink'
                        }`}
                      >
                        {active && <span className="absolute left-0 top-1.5 h-[calc(100%-12px)] w-0.5 rounded-full bg-accent" />}
                        <Icon size={15} className={active ? 'text-accent' : 'text-faint'} />
                        <span className="truncate">{item.label}</span>
                      </a>
                    </li>
                  )
                })}
              </ul>
            </div>
          ))}
        </nav>

        <div className="border-t border-line px-5 py-3">
          <div className="truncate text-[12px] text-muted">{email}</div>
          <button type="button" onClick={onLogout} className="mt-1 flex items-center gap-1.5 text-[12px] text-muted transition-colors hover:text-ink">
            <LogOut size={13} />
            Sign out
          </button>
        </div>
      </aside>

      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}
