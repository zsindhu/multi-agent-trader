/**
 * Pipeline spine strip (design 5a compact / 3a expanded): the six funnel
 * stages with ▶ separators, sweep-time note, regime + LLM-spend boxes.
 */
import { MONO, UI } from '../lib/design'
import { StatBox } from './bits'

function StageBox({ label, count, sub, detail, bg = '#c0c0c0', color = '#000', labelColor = '#606060', expanded }) {
  return (
    <div style={{ border: '2px outset #dfdfdf', background: bg, padding: '4px 10px', minWidth: 96, flex: expanded ? 1 : 'none' }}>
      <div style={{ fontSize: 9, fontFamily: UI, color: labelColor, textTransform: 'uppercase', letterSpacing: '0.5px' }}>{label}</div>
      <div style={{ fontFamily: MONO, fontSize: 16, fontWeight: 'bold', color }}>{count ?? '--'}</div>
      <div style={{ fontSize: 9, fontFamily: UI, color: labelColor }}>{sub}</div>
      {expanded && detail && (
        <div style={{ borderTop: '1px solid #a0a0a0', marginTop: 3, paddingTop: 2, fontFamily: MONO, fontSize: 9, color: labelColor }}>{detail}</div>
      )}
    </div>
  )
}

const Sep = () => <span style={{ fontFamily: MONO, fontSize: 14, color: '#808080', padding: '0 4px', alignSelf: 'center' }}>{'▶'}</span>

export default function SpineStrip({ stages, sweepNote, regime, llmSpend, expanded = false }) {
  return (
    <div style={{ background: '#d4d0c8', borderBottom: '2px outset #dfdfdf', padding: '6px 8px' }}>
      <div style={{ display: 'flex', alignItems: 'stretch', gap: 0, overflowX: 'auto' }}>
        {stages.map((s, i) => (
          <div key={s.label} style={{ display: 'flex', alignItems: 'stretch', flex: expanded ? 1 : 'none' }}>
            <StageBox {...s} expanded={expanded} />
            {i < stages.length - 1 && <Sep />}
          </div>
        ))}
        {sweepNote && (
          <span style={{ fontFamily: UI, fontSize: 9, color: '#606060', alignSelf: 'flex-end', padding: '0 6px 2px', whiteSpace: 'nowrap' }}>
            {sweepNote}
          </span>
        )}
        <div style={{ flex: expanded ? 'none' : 1 }} />
        {regime != null && (
          <div style={{ marginRight: 4, display: 'flex' }}>
            <StatBox label="Regime" value={(regime || 'unknown').toUpperCase()} valueColor="#808000" />
          </div>
        )}
        {llmSpend != null && <StatBox label="LLM spend today" value={`$${Number(llmSpend).toFixed(2)}`} dark />}
      </div>
    </div>
  )
}
