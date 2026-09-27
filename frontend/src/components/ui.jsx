// The pieces every page is built from, and the type scale they agree on:
//
//   page title 20px semibold · page description 13px muted
//   section title 13px medium · body 13px · small 12px · caption 11.5px faint
//
// Structure is drawn with rules and whitespace. A bordered box is used only
// where the thing on screen is an object in its own right — a proposal, a
// handoff card, a turn's evidence — not as a wrapper for every block.

export function Page({ title, subtitle, sample = false, actions, children }) {
  return (
    <div className="h-full overflow-y-auto bg-surface">
      <div className="mx-auto w-full max-w-[1180px] px-8 py-8">
        <div className="mb-7 flex items-start justify-between gap-6 border-b border-line pb-5">
          <div className="min-w-0">
            <h1 className="text-[20px] font-semibold leading-tight text-ink">{title}</h1>
            {subtitle && <p className="mt-1.5 max-w-[680px] text-[13px] leading-relaxed text-muted">{subtitle}</p>}
            {sample && <p className="mt-2 text-[12px] text-faint">Sample data. Nothing on this page is connected to a backend yet.</p>}
          </div>
          {actions && <div className="flex flex-shrink-0 items-center gap-2">{actions}</div>}
        </div>
        {children}
      </div>
    </div>
  )
}

export function Card({ title, extra, children, className = '', plain = false }) {
  if (plain) {
    return (
      <section className={className}>
        {(title || extra) && <SectionHead title={title} extra={extra} />}
        {children}
      </section>
    )
  }
  return (
    <section className={`rounded-lg border border-line bg-surface ${className}`}>
      {(title || extra) && (
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <h2 className="text-[13px] font-medium text-ink">{title}</h2>
          {extra && <div className="text-[12px] text-muted">{extra}</div>}
        </div>
      )}
      <div className="p-4">{children}</div>
    </section>
  )
}

export function SectionHead({ title, extra }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="text-[13px] font-medium text-ink">{title}</h2>
      {extra && <div className="text-[12px] text-muted">{extra}</div>}
    </div>
  )
}

export function Table({ columns, rows, keyField = 'id', onRowClick, selectedKey }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="border-b border-line text-left text-[12px] text-muted">
            {columns.map((column) => (
              <th key={column.key} className={`px-2 py-2 font-medium ${column.align === 'right' ? 'text-right' : ''}`}>
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = row[keyField]
            const selected = selectedKey != null && key === selectedKey
            return (
              <tr
                key={key}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={`border-b border-line last:border-b-0 ${onRowClick ? 'cursor-pointer hover:bg-hover' : ''} ${selected ? 'bg-hover' : ''}`}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={`px-2 py-2.5 align-top text-ink ${column.align === 'right' ? 'text-right' : ''} ${column.mono ? 'font-mono text-[12px]' : ''}`}
                  >
                    {column.render ? column.render(row) : row[column.key]}
                  </td>
                ))}
              </tr>
            )
          })}
          {rows.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="px-2 py-8 text-center text-[13px] text-faint">
                Nothing here yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

// Tones carry meaning, not decoration: the accent for what is live, chosen
// or confirmed; the outline for a neutral fact; red text only for a failure.
const TONES = {
  neutral: 'bg-hover text-muted',
  outline: 'border border-line text-muted',
  accent: 'bg-accent-tint text-accent',
  ink: 'bg-accent text-white',
  green: 'bg-accent-tint text-accent',
  amber: 'border border-line text-muted',
  red: 'border border-danger/30 text-danger',
}

export function Tag({ tone = 'neutral', children, className = '' }) {
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-px text-[11.5px] font-medium leading-5 ${TONES[tone]} ${className}`}>
      {children}
    </span>
  )
}

export function Mock() {
  return <span className="ml-2 text-[11.5px] font-normal text-faint">sample</span>
}

// A warning or a note: a rule on the left in the accent, plain text beside
// it. Never a tinted box.
export function Notice({ children, tone = 'accent' }) {
  const rule = tone === 'danger' ? 'border-danger' : 'border-accent'
  return (
    <div className={`border-l-2 ${rule} py-0.5 pl-3 text-[13px] leading-relaxed text-ink`}>{children}</div>
  )
}

export function Tabs({ tabs, active, onChange }) {
  return (
    <div className="mb-5 flex gap-4 border-b border-line">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={() => onChange(tab.id)}
          className={`-mb-px border-b-2 pb-2 pt-1 text-[13px] transition-colors ${
            active === tab.id ? 'border-accent font-medium text-ink' : 'border-transparent text-muted hover:text-ink'
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}

export function Stat({ label, value, hint }) {
  return (
    <div className="border-l border-line pl-4">
      <div className="text-[12px] text-muted">{label}</div>
      <div className="mt-0.5 text-[22px] font-semibold leading-tight text-ink">{value}</div>
      {hint && <div className="mt-0.5 text-[11.5px] text-faint">{hint}</div>}
    </div>
  )
}

const BUTTONS = {
  primary: 'bg-accent text-white hover:bg-[#274d73] disabled:opacity-40',
  secondary: 'border border-line bg-surface text-ink hover:bg-hover disabled:opacity-40',
  danger: 'border border-line bg-surface text-danger hover:bg-hover disabled:opacity-40',
  ghost: 'text-muted hover:bg-hover hover:text-ink disabled:opacity-40',
}

export function Button({ variant = 'secondary', size = 'md', className = '', children, ...props }) {
  const pad = size === 'sm' ? 'h-7 px-2.5 text-[12px]' : 'h-8 px-3.5 text-[13px]'
  return (
    <button
      type="button"
      className={`inline-flex items-center gap-1.5 rounded-md font-medium transition-colors ${pad} ${BUTTONS[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  )
}

export function Toggle({ on, onChange, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={onChange}
      className={`relative inline-flex h-5 w-9 flex-shrink-0 items-center rounded-full transition-colors ${on ? 'bg-accent' : 'bg-line-2'}`}
    >
      <span className={`absolute left-0.5 h-4 w-4 rounded-full bg-white transition-transform ${on ? 'translate-x-4' : 'translate-x-0'}`} />
    </button>
  )
}

export const inputClass =
  'w-full rounded-md border border-line bg-white px-3 py-2 text-[13px] text-ink placeholder:text-faint outline-none transition focus:border-accent focus:shadow-input'

export function Kv({ rows }) {
  return (
    <dl className="grid grid-cols-[132px_1fr] gap-y-1.5 text-[13px]">
      {rows.map(([k, v]) => (
        <Row key={k} k={k} v={v} />
      ))}
    </dl>
  )
}

function Row({ k, v }) {
  return (
    <>
      <dt className="text-muted">{k}</dt>
      <dd className="min-w-0 break-words text-ink">{v}</dd>
    </>
  )
}
