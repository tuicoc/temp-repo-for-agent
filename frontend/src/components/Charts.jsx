// Two small charts in plain SVG, sized by their container through viewBox.
//
// One accent carries every chart: the system's series is a filled bar in
// the accent, the reference series (a baseline, a p95) is an outlined bar
// with a hatch, so the two are told apart by texture and not by colour
// alone. Every bar is labelled, because these charts exist to compare exact
// figures and the table beside them says the same numbers. Grid lines are
// recessive; the baseline of the axis is the only strong line.

const ACCENT = '#2F5D8A'
const GREY = '#9AA0A6'
const RULE = '#E1E3E6'
const INK = '#000000'
const MUTED = '#5F6368'

function Hatch({ id }) {
  return (
    <pattern id={id} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <line x1="0" y1="0" x2="0" y2="6" stroke={GREY} strokeWidth="1.5" />
    </pattern>
  )
}

// A bar with only its data end rounded, anchored to the baseline.
function bar(x, y, w, h, r = 3) {
  if (h <= 0) return ''
  const rr = Math.min(r, w / 2, h)
  return `M${x},${y + h} V${y + rr} Q${x},${y} ${x + rr},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h} Z`
}

export function GroupedBars({ groups, series, max, format = (v) => String(v), height = 220 }) {
  const width = 560
  const pad = { top: 28, right: 12, bottom: 34, left: 40 }
  const innerW = width - pad.left - pad.right
  const innerH = height - pad.top - pad.bottom
  const top = max ?? Math.max(...groups.flatMap((g) => [g.a, g.b])) * 1.15
  const groupW = innerW / groups.length
  const barW = Math.min(28, (groupW - 16) / 2)
  const y = (v) => pad.top + innerH - (v / top) * innerH
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * top)
  const patternId = `hatch-${series[0].replace(/\s+/g, '-').toLowerCase()}`

  return (
    <figure>
      <div className="mb-2 flex items-center gap-4 text-[12px] text-muted">
        <span className="inline-flex items-center gap-1.5">
          <svg width="14" height="10" aria-hidden="true">
            <defs><Hatch id={`${patternId}-legend`} /></defs>
            <rect x="0.5" y="0.5" width="13" height="9" fill={`url(#${patternId}-legend)`} stroke={GREY} />
          </svg>
          {series[0]}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <svg width="14" height="10" aria-hidden="true"><rect width="14" height="10" fill={ACCENT} /></svg>
          {series[1]}
        </span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" role="img" aria-label={`${series[0]} against ${series[1]}`}>
        <defs><Hatch id={patternId} /></defs>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.left} x2={width - pad.right} y1={y(t)} y2={y(t)} stroke={t === 0 ? MUTED : RULE} strokeWidth="1" />
            <text x={pad.left - 6} y={y(t) + 4} textAnchor="end" fontSize="10" fill={MUTED}>{format(t)}</text>
          </g>
        ))}
        {groups.map((g, i) => {
          const gx = pad.left + i * groupW + (groupW - (barW * 2 + 2)) / 2
          const ay = y(g.a)
          const by = y(g.b)
          return (
            <g key={g.label}>
              <path d={bar(gx, ay, barW, y(0) - ay)} fill={`url(#${patternId})`} stroke={GREY} strokeWidth="1">
                <title>{`${g.label}, ${series[0]}: ${format(g.a)}`}</title>
              </path>
              <text x={gx + barW / 2} y={ay - 5} textAnchor="middle" fontSize="10" fill={MUTED}>{format(g.a)}</text>
              <path d={bar(gx + barW + 2, by, barW, y(0) - by)} fill={ACCENT}>
                <title>{`${g.label}, ${series[1]}: ${format(g.b)}`}</title>
              </path>
              <text x={gx + barW + 2 + barW / 2} y={by - 5} textAnchor="middle" fontSize="10" fontWeight="600" fill={INK}>{format(g.b)}</text>
              <text x={pad.left + i * groupW + groupW / 2} y={height - 12} textAnchor="middle" fontSize="11" fill={INK}>{g.label}</text>
            </g>
          )
        })}
      </svg>
    </figure>
  )
}

// One measure across rounds, with two horizontal references: where the
// baseline stands and where the threshold is.
export function RoundsLine({ points, references = [], format = (v) => String(v), height = 200 }) {
  const width = 560
  const pad = { top: 20, right: 60, bottom: 30, left: 40 }
  const innerW = width - pad.left - pad.right
  const innerH = height - pad.top - pad.bottom
  const values = [...points.map((p) => p.value), ...references.map((r) => r.value)]
  const top = Math.max(...values) * 1.15
  const y = (v) => pad.top + innerH - (v / top) * innerH
  const x = (i) => pad.left + (points.length === 1 ? innerW / 2 : (i / (points.length - 1)) * innerW)
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(p.value)}`).join(' ')
  const ticks = [0, 0.5, 1].map((f) => f * top)

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" role="img" aria-label="Metric across rounds">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={pad.left} x2={width - pad.right} y1={y(t)} y2={y(t)} stroke={t === 0 ? MUTED : RULE} />
          <text x={pad.left - 6} y={y(t) + 4} textAnchor="end" fontSize="10" fill={MUTED}>{format(t)}</text>
        </g>
      ))}
      {references.map((r) => (
        <g key={r.label}>
          <line x1={pad.left} x2={width - pad.right} y1={y(r.value)} y2={y(r.value)} stroke={GREY} strokeDasharray="4 4" />
          <text x={width - pad.right + 6} y={y(r.value) + 4} fontSize="10" fill={MUTED}>{r.label} {format(r.value)}</text>
        </g>
      ))}
      <path d={path} fill="none" stroke={ACCENT} strokeWidth="2" />
      {points.map((p, i) => (
        <g key={p.label}>
          <circle cx={x(i)} cy={y(p.value)} r="5" fill="#FFFFFF" stroke={ACCENT} strokeWidth="2">
            <title>{`${p.label}: ${format(p.value)}`}</title>
          </circle>
          <text x={x(i)} y={y(p.value) - 10} textAnchor="middle" fontSize="10" fontWeight="600" fill={INK}>{format(p.value)}</text>
          <text x={x(i)} y={height - 10} textAnchor="middle" fontSize="11" fill={INK}>{p.label}</text>
        </g>
      ))}
    </svg>
  )
}
