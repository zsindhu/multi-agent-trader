/**
 * Digestible daily reflection (design 4d) — three takeaways / changed since
 * yesterday / watching tomorrow, with the full prose one click away.
 * Degrades honestly when the structured summary is missing.
 */
import { useEffect, useState } from 'react'
import Panel from './Panel'
import { MONO, UI, fmtTimeET } from '../lib/design'
import { fetchDashboardReflection } from '../api'

const SECTION = {
  fontFamily: UI, fontSize: 9, color: '#808080',
  textTransform: 'uppercase', letterSpacing: '0.5px',
}
const SECTION_DIVIDED = { ...SECTION, margin: '6px 0 3px', borderTop: '1px solid #d0d0d0', paddingTop: 4 }
const VALENCE_COLORS = { positive: '#008000', neutral: '#808000', negative: '#ff0000' }

function wordCount(text) {
  return (text || '').trim().split(/\s+/).filter(Boolean).length
}

function fmtStamp(reflection) {
  if (!reflection?.timestamp) return '--'
  if (reflection.is_today) return fmtTimeET(reflection.timestamp)
  const d = new Date(reflection.timestamp)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).toUpperCase()
}

function FullReflectionExpander({ body }) {
  const [open, setOpen] = useState(false)
  if (!body) return null
  return (
    <div style={{ marginTop: 5, borderTop: '1px solid #d0d0d0', paddingTop: 4 }}>
      <div
        style={{ fontFamily: UI, fontSize: 10, color: '#000080', cursor: 'pointer' }}
        onClick={() => setOpen(!open)}
      >
        {'▶'} {open ? 'Hide' : 'Full'} reflection ({wordCount(body)} words)
      </div>
      {open && (
        <div style={{ fontFamily: MONO, fontSize: 10, lineHeight: 1.5, color: '#404040', whiteSpace: 'pre-wrap', marginTop: 4 }}>
          {body}
        </div>
      )}
    </div>
  )
}

function ChangeLine({ line }) {
  const marker = (line || '').trim().charAt(0)
  const color = marker === '+' ? '#008000' : marker === '~' ? '#808000' : '#000'
  return (
    <div>
      <span style={{ color, fontWeight: 'bold' }}>{marker}</span>
      <span>{(line || '').trim().slice(1)}</span>
    </div>
  )
}

function StructuredBody({ reflection }) {
  const s = reflection.structured
  const takeaways = Array.isArray(s.takeaways) ? s.takeaways : []
  const changes = Array.isArray(s.changes) ? s.changes : []
  return (
    <div>
      <div style={{ ...SECTION, marginBottom: 3 }}>Three takeaways</div>
      {takeaways.length === 0 && (
        <div style={{ fontFamily: UI, fontSize: 10, color: '#808080' }}>No takeaways in this reflection.</div>
      )}
      {takeaways.map((t, i) => (
        <div key={i} style={{ display: 'flex', gap: 5, padding: '2px 0', fontFamily: UI, fontSize: 10, lineHeight: 1.4 }}>
          <span style={{ fontFamily: MONO, fontWeight: 'bold', color: VALENCE_COLORS[t.valence] || '#808000' }}>{i + 1}</span>
          <span><b>{t.lead}</b>{t.sentence ? <> — {t.sentence}</> : null}</span>
        </div>
      ))}

      <div style={SECTION_DIVIDED}>Changed since yesterday</div>
      {changes.length === 0
        ? <div style={{ fontFamily: UI, fontSize: 10, color: '#808080' }}>No changes recorded.</div>
        : (
          <div style={{ fontFamily: MONO, fontSize: 10, lineHeight: 1.6 }}>
            {changes.map((c, i) => <ChangeLine key={i} line={c} />)}
          </div>
        )}

      <div style={SECTION_DIVIDED}>Watching tomorrow</div>
      <div style={{ fontFamily: UI, fontSize: 10, lineHeight: 1.5 }}>
        {s.watching || <span style={{ color: '#808080' }}>Nothing flagged.</span>}
      </div>

      <FullReflectionExpander body={reflection.body} />
    </div>
  )
}

function DegradedBody({ reflection }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <div style={{ fontFamily: UI, fontSize: 10, color: '#808080', marginBottom: 4 }}>
        Structured summary not available for this reflection
      </div>
      <div style={{ fontFamily: MONO, fontSize: 10, lineHeight: 1.5, color: '#404040', whiteSpace: 'pre-wrap', maxHeight: open ? 'none' : 64, overflow: 'hidden' }}>
        {reflection.body}
      </div>
      <div style={{ marginTop: 4, fontFamily: UI, fontSize: 10, color: '#000080', cursor: 'pointer' }} onClick={() => setOpen(!open)}>
        {'▶'} {open ? 'Collapse' : `Full reflection (${wordCount(reflection.body)} words)`}
      </div>
    </div>
  )
}

export default function ReflectionCard() {
  const [reflection, setReflection] = useState(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    fetchDashboardReflection().then(setReflection).catch(() => setError(true))
  }, [])

  let body
  if (error) {
    body = <div style={{ fontFamily: UI, fontSize: 10, color: '#808080' }}>Reflection unavailable — API error.</div>
  } else if (!reflection) {
    body = <div style={{ fontFamily: UI, fontSize: 10, color: '#808080' }}>Loading…</div>
  } else if (!reflection.body) {
    body = <div style={{ fontFamily: UI, fontSize: 10, color: '#808080' }}>No reflection recorded yet — the Research Analyst writes one after the close.</div>
  } else if (reflection.structured) {
    body = <StructuredBody reflection={reflection} />
  } else {
    body = <DegradedBody reflection={reflection} />
  }

  return (
    <Panel title="Daily Reflection — Research Analyst" right={fmtStamp(reflection)}>
      {body}
    </Panel>
  )
}
