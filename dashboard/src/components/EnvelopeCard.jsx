import { useState } from 'react'
import { MONO, UI, sleeveInfo } from '../lib/design'

/**
 * Judgment envelope card (design 4a) — renders the structured judgment
 * {verdict, one_liner, factors, confidence} beside (never instead of) prose.
 * Three states: single envelope, per-sleeve grid, degraded (prose-only).
 */

const VERDICT_COLORS = {
  // verdicts are free-form snake_case labels; color by family
  open: { bg: '#008000', border: '#004000' },
  hold: { bg: '#808000', border: '#404000' },
  pass: { bg: '#808080', border: '#404040' },
}

function verdictColor(verdict) {
  const v = (verdict || '').toLowerCase()
  if (v.includes('open') || v.includes('entr') || v.includes('sell') || v.includes('buy')) return VERDICT_COLORS.open
  if (v.includes('hold') || v.includes('watch') || v.includes('select')) return VERDICT_COLORS.hold
  return VERDICT_COLORS.pass
}

export function VerdictChip({ verdict, small = false }) {
  const c = verdictColor(verdict)
  return (
    <span style={{
      fontFamily: UI, fontSize: small ? 9 : 10, fontWeight: 'bold',
      padding: small ? '0 6px' : '1px 8px', background: c.bg, color: '#fff',
      border: small ? 'none' : `1px solid ${c.border}`, textTransform: 'uppercase', whiteSpace: 'nowrap',
    }}>
      {(verdict || 'n/a').replace(/_/g, ' ')}
    </span>
  )
}

function FactorChip({ factor }) {
  const dir = (factor.direction || 'neutral').toLowerCase()
  const supporting = ['bullish', 'for', 'up', 'positive'].some((d) => dir.includes(d))
  const opposing = ['bearish', 'against', 'down', 'negative'].some((d) => dir.includes(d))
  const w = factor.weight
  const strong = w != null && w >= 0.25
  const style = supporting
    ? strong
      ? { border: '1px solid #008000', background: '#e8ffe8', color: '#000' }
      : { border: '1px solid #80b080', background: '#f0fff0', color: '#406040' }
    : opposing
      ? { border: '1px solid #b08080', background: '#fff0f0', color: '#604040' }
      : { border: '1px solid #d0d0d0', background: '#fff', color: '#404040' }
  return (
    <span style={{ fontFamily: MONO, fontSize: 10, padding: '1px 6px', ...style }}>
      {factor.signal} {supporting ? '▲' : opposing ? '▼' : '●'}{w != null ? ` ${w.toFixed(2)}` : ''}
    </span>
  )
}

function ReasoningExpander({ text }) {
  const [open, setOpen] = useState(false)
  if (!text) return null
  const words = text.trim().split(/\s+/).length
  return (
    <div style={{ marginTop: 6, borderTop: '1px solid #d0d0d0', paddingTop: 4 }}>
      <div
        style={{ fontFamily: UI, fontSize: 10, color: '#000080', cursor: 'pointer' }}
        onClick={() => setOpen(!open)}
      >
        {'▶'} {open ? 'Hide' : 'Show'} full reasoning ({words} words)
      </div>
      {open && (
        <div style={{ fontFamily: MONO, fontSize: 10, lineHeight: 1.5, color: '#404040', whiteSpace: 'pre-wrap', marginTop: 4 }}>
          {text}
        </div>
      )}
    </div>
  )
}

/** Single-envelope body (used inside a Panel or standalone card). */
export function EnvelopeBody({ envelope, fullText }) {
  const conf = envelope?.confidence
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <VerdictChip verdict={envelope?.verdict} />
        <span style={{ fontSize: 11, fontFamily: UI, flex: 1 }}>{envelope?.one_liner || '(no one-liner)'}</span>
      </div>
      {conf != null && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 5 }}>
          <span style={{ fontFamily: UI, fontSize: 9, color: '#808080', width: 64, textAlign: 'right' }}>CONFIDENCE</span>
          <div style={{ flex: 1, height: 10, border: '1px inset #dfdfdf', background: '#d4d0c8', position: 'relative' }}>
            <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${Math.min(100, conf * 100)}%`, background: '#008000' }} />
          </div>
          <span style={{ fontFamily: MONO, fontSize: 10, fontWeight: 'bold' }}>{Number(conf).toFixed(2)}</span>
        </div>
      )}
      {(envelope?.factors || []).length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginTop: 5 }}>
          {envelope.factors.map((f, i) => <FactorChip key={i} factor={f} />)}
        </div>
      )}
      <ReasoningExpander text={fullText} />
    </div>
  )
}

/** Degraded body — envelope failed validation; raw prose is the content. */
export function DegradedBody({ fullText }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <div style={{ fontFamily: UI, fontSize: 10, color: '#808080', marginBottom: 4 }}>
        {'⚠'} Structured envelope failed validation — showing raw reasoning.
      </div>
      <div style={{ fontFamily: MONO, fontSize: 10, lineHeight: 1.5, color: '#404040', maxHeight: open ? 'none' : 56, overflow: 'hidden', whiteSpace: 'pre-wrap' }}>
        {fullText || '(no reasoning recorded)'}
      </div>
      <div style={{ marginTop: 4, fontFamily: UI, fontSize: 10, color: '#000080', cursor: 'pointer' }} onClick={() => setOpen(!open)}>
        {'▶'} {open ? 'Collapse' : 'Expand'}
      </div>
    </div>
  )
}

/** Per-sleeve grid body for orchestrator cycles. */
export function SleeveEnvelopeGrid({ sleeveEnvelopes }) {
  const entries = Object.entries(sleeveEnvelopes || {})
  if (!entries.length) return null
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
      {entries.map(([sid, env]) => (
        <div key={sid} style={{ border: '1px solid #c0c0c0', padding: '4px 6px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <VerdictChip verdict={env?.degraded ? 'degraded' : env?.verdict} small />
            <span style={{ fontFamily: UI, fontSize: 10, fontWeight: 'bold', flex: 1 }}>{sleeveInfo(sid).name}</span>
            <span style={{ fontFamily: MONO, fontSize: 9, color: '#808080' }}>
              {env?.confidence != null ? Number(env.confidence).toFixed(2) : '--'}
            </span>
          </div>
          <div style={{ fontFamily: UI, fontSize: 10, marginTop: 3, lineHeight: 1.4 }}>
            {env?.one_liner || (env?.degraded ? 'Envelope degraded — see full reasoning.' : '(no one-liner)')}
          </div>
        </div>
      ))}
    </div>
  )
}

/**
 * Full cycle card: picks the right state from a /dashboard/cycles row.
 */
export default function EnvelopeCard({ cycle }) {
  const env = cycle.envelope
  const sleeveEnvs = cycle.sleeve_envelopes
  const hasSleeves = sleeveEnvs && Object.keys(sleeveEnvs).length > 0
  const degraded = !hasSleeves && (!env || env.degraded)
  const time = cycle.timestamp ? new Date(cycle.timestamp) : null
  const et = time ? new Date(time.getTime() - 4 * 3600 * 1000) : null
  const hhmm = et ? `${String(et.getUTCHours()).padStart(2, '0')}:${String(et.getUTCMinutes()).padStart(2, '0')}` : '--:--'
  const title = `Cycle ${hhmm}${hasSleeves ? ` — Orchestrator · ${Object.keys(sleeveEnvs).length} sleeve envelopes` : ''}`
  const right = degraded
    ? 'ENVELOPE DEGRADED'
    : `$${(cycle.llm_cost_usd || 0).toFixed(4)}${cycle.llm_model ? ` · ${cycle.llm_model.split('/').pop()}` : ''}`

  return (
    <div style={{ border: '2px outset #dfdfdf', background: '#c0c0c0' }}>
      <div style={{ background: degraded ? '#808080' : '#000080', color: '#fff', fontSize: 12, fontWeight: 'bold', padding: '2px 4px', display: 'flex', fontFamily: UI }}>
        <span style={{ flex: 1 }}>{title}</span>
        <span style={{ fontWeight: 'normal', fontSize: 10, color: degraded ? '#e0e0e0' : '#a0a0ff' }}>{right}</span>
      </div>
      <div style={{ border: '2px inset #dfdfdf', margin: 2, background: '#fff', padding: hasSleeves ? 4 : 6 }}>
        {hasSleeves
          ? <SleeveEnvelopeGrid sleeveEnvelopes={sleeveEnvs} />
          : degraded
            ? <DegradedBody fullText={cycle.reasoning} />
            : <EnvelopeBody envelope={env} fullText={cycle.reasoning} />}
      </div>
    </div>
  )
}
