/**
 * Small shared redesign pieces: sleeve badge, segmented learning progress,
 * terminal feed, stat boxes, bar meter.
 */
import { MONO, UI, sleeveInfo } from '../lib/design'

export function SleeveBadge({ id, full = false }) {
  const s = sleeveInfo(id)
  return (
    <span
      title={s.name}
      style={{
        fontFamily: UI, fontSize: 9, textTransform: 'uppercase',
        border: '1px solid #808080', background: s.bg, padding: '0 4px', whiteSpace: 'nowrap',
      }}
    >
      {full ? s.name : s.tag}
    </span>
  )
}

/** 3-state segmented progress bar (design 4b): clean navy, unknown olive, rest empty. */
export function SegmentedProgress({ clean = 0, unknown = 0, total = 50 }) {
  const segs = []
  for (let i = 0; i < total; i++) {
    const bg = i < clean ? '#000080' : i < clean + unknown ? '#c0c000' : 'transparent'
    segs.push(<div key={i} style={{ flex: 1, background: bg }} />)
  }
  return (
    <div style={{ height: 14, border: '2px inset #dfdfdf', background: '#d4d0c8', display: 'flex', gap: 1, padding: 1 }}>
      {segs}
    </div>
  )
}

/** Legend swatch row for the segmented bar. */
export function ProgressLegend({ clean, unknown }) {
  const Sw = ({ bg, border }) => (
    <span style={{ width: 8, height: 8, background: bg, border: border || 'none', display: 'inline-block' }} />
  )
  return (
    <div style={{ display: 'flex', gap: 10, marginTop: 5, fontFamily: UI, fontSize: 9 }}>
      <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}><Sw bg="#000080" />clean ({clean})</span>
      <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}><Sw bg="#c0c000" />unknown evidence ({unknown})</span>
      <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}><Sw bg="#d4d0c8" border="1px solid #a0a0a0" />remaining</span>
    </div>
  )
}

const ACTIVITY_COLORS = {
  fill: '#00ff00', recon: '#00ff00', risk: '#00c000',
  warn: '#ffff00', trade: '#ffffff', routine: '#c0c0c0',
}

export function activityKind(e) {
  const t = `${e.action_type || ''} ${e.outcome || ''}`.toLowerCase()
  if (t.includes('fail') || t.includes('error') || t.includes('flag') || t.includes('reject')) return 'warn'
  if (t.includes('fill') || t.includes('reconcil')) return 'fill'
  if (t.includes('risk') || t.includes('gate')) return 'risk'
  if (t.includes('trade') || t.includes('execut') || t.includes('conflict')) return 'trade'
  return 'routine'
}

/** Black terminal feed. rows: [{time, agent, text, kind}] */
export function TerminalFeed({ rows, emptyText = 'No activity yet.' }) {
  return (
    <div style={{ background: '#000', padding: '4px 6px', fontFamily: MONO, fontSize: 10, lineHeight: 1.6, height: '100%', overflowY: 'auto' }}>
      {rows.length === 0 && <div style={{ color: '#606060' }}>{emptyText}</div>}
      {rows.map((r, i) => (
        <div key={i} style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          <span style={{ color: '#606060' }}>{r.time} </span>
          <span style={{ color: '#00c0c0' }}>[{r.agent}] </span>
          <span style={{ color: ACTIVITY_COLORS[r.kind] || '#c0c0c0' }}>{r.text}</span>
        </div>
      ))}
    </div>
  )
}

/** White (or black terminal) inset stat box for strips. */
export function StatBox({ label, value, valueColor = '#000', dark = false, sub }) {
  return (
    <div style={{
      border: '2px inset #dfdfdf', background: dark ? '#000' : '#fff',
      padding: '4px 10px', display: 'flex', flexDirection: 'column', justifyContent: 'center',
    }}>
      <div style={{ fontSize: 9, fontFamily: UI, color: dark ? '#00c000' : '#808080', textTransform: 'uppercase' }}>{label}</div>
      <div style={{ fontFamily: MONO, fontSize: 16, fontWeight: 'bold', color: dark ? '#00ff00' : valueColor }}>{value}</div>
      {sub && <div style={{ fontSize: 9, fontFamily: UI, color: dark ? '#00c000' : '#808080' }}>{sub}</div>}
    </div>
  )
}

/** Horizontal bar meter: navy capital / green-red pnl. */
export function BarMeter({ pct, color = '#000080', height = 8 }) {
  return (
    <div style={{ height, border: '1px inset #dfdfdf', background: '#d4d0c8', position: 'relative', flex: 1 }}>
      <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${Math.max(0, Math.min(100, pct))}%`, background: color }} />
    </div>
  )
}
