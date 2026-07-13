/**
 * Agents (admin-only) — design 3c.
 * Integrity strip + DB write audit / overwrite detection / per-agent cost /
 * message bus, with sleeve conflicts (7d) spanning below.
 * Panels whose backend doesn't exist yet render honest empty states.
 */
import { useState, useEffect, useCallback } from 'react'
import Panel from '../components/Panel'
import { StatBox, BarMeter } from '../components/bits'
import { MONO, UI, fmtTimeET } from '../lib/design'
import { fetchAgentCosts, fetchMessageBus, fetchConflicts, fetchReconciliation } from '../api'

const OLIVE = '#808000'
const GREEN = '#008000'

// resolution_mode → badge background (all bordered 1px solid #808080)
function badgeBg(mode) {
  const m = (mode || '').toUpperCase()
  if (m === 'LLM_JUDGED') return '#e8e8ff'
  return '#f0f0f0' // DETERMINISTIC, FALLBACK_LOAD_BALANCE, unknown
}

function ModeBadge({ mode }) {
  return (
    <span style={{
      fontFamily: UI, fontSize: 9, textTransform: 'uppercase', whiteSpace: 'nowrap',
      border: '1px solid #808080', background: badgeBg(mode), padding: '0 4px',
    }}>
      {(mode || 'unknown').toUpperCase()}
    </span>
  )
}

// ── Integrity strip ──────────────────────────────────────────

function IntegrityStrip({ costs, recon }) {
  const report = recon === undefined ? undefined : (recon?.report ?? null)

  const llmCostToday = costs?.today
    ? '$' + costs.today.reduce((s, r) => s + (r.cost_usd || 0), 0).toFixed(2)
    : costs === null ? 'ERR' : '--'

  let integrityValue = '--'
  let integrityColor = '#808080'
  let integritySub
  if (report === null) {
    integritySub = 'no report yet'
  } else if (report) {
    if (report.ok) {
      integrityValue = `PASS ${fmtTimeET(report.ran_at)}`
      integrityColor = GREEN
    } else {
      integrityValue = `${report.discrepancy_count} ISSUES`
      integrityColor = OLIVE
    }
  }

  let ghostValue = '--'
  let ghostColor = '#808080'
  if (report) {
    const ghosts = (report.discrepancies || []).filter(d => d.kind === 'order_missing_at_broker').length
    ghostValue = String(ghosts)
    ghostColor = ghosts === 0 ? GREEN : OLIVE
  }

  return (
    <div style={{ background: '#d4d0c8', borderBottom: '2px outset #dfdfdf', padding: '6px 8px', display: 'flex', gap: 4, flexWrap: 'wrap' }}>
      <StatBox label="DB Writes Today" value="--" sub="Integrity Sentinel not built" />
      <StatBox label="Overwrites" value="--" sub="Integrity Sentinel not built" />
      <StatBox label="LLM Cost Today" value={llmCostToday} />
      <StatBox label="Integrity Check" value={integrityValue} valueColor={integrityColor} sub={integritySub} />
      <StatBox label="Ghost Trades" value={ghostValue} valueColor={ghostColor} sub="orders missing at broker" />
    </div>
  )
}

// ── (a) DB Write Audit — backend not built yet ───────────────

function WriteAuditPanel() {
  const th = {
    background: '#000080', color: '#fff', fontFamily: UI, fontSize: 10,
    padding: '2px 6px', textAlign: 'left', border: '1px solid #808080',
  }
  return (
    <Panel title="DB Write Audit — by agent × table (today)" bodyPad={0} style={{ minHeight: 0 }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10, fontFamily: MONO }}>
        <thead>
          <tr>
            <th style={th}>AGENT</th>
            <th style={th}>TABLE</th>
            <th style={{ ...th, textAlign: 'right' }}>INS</th>
            <th style={{ ...th, textAlign: 'right' }}>UPD</th>
            <th style={th}>FLAG</th>
          </tr>
        </thead>
      </table>
      <div style={{ padding: '10px 8px', fontFamily: UI, fontSize: 11, color: '#808080' }}>
        {'⚠'} Write-audit instrumentation ships with the Integrity Sentinel (BACKLOG). Nothing to show yet.
      </div>
    </Panel>
  )
}

// ── (b) Overwrite Detection — remediation status ─────────────

function OverwritePanel() {
  const lines = [
    '✓ name_observations — append-only since Jul 12 (sweep_id)',
    '✓ trade_outcomes — labeler insert-only',
    '✓ tier2b reasoning — write-once columns',
  ]
  return (
    <Panel title="Overwrite Detection — data muddying watch" style={{ minHeight: 0 }}>
      <div style={{ fontFamily: MONO, fontSize: 10, lineHeight: 1.6 }}>
        {lines.map(l => <div key={l} style={{ color: GREEN }}>{l}</div>)}
        <div style={{ color: '#808080', fontFamily: UI, marginTop: 6 }}>
          Automated overwrite diffs ship with the Integrity Sentinel.
        </div>
      </div>
    </Panel>
  )
}

// ── (c) Per-Agent Cost ───────────────────────────────────────

function CostPanel({ costs }) {
  if (costs === undefined) {
    return <Panel title="Per-Agent Cost (today)"><div style={{ fontFamily: UI, fontSize: 11, color: '#808080' }}>Loading...</div></Panel>
  }
  if (costs === null) {
    return <Panel title="Per-Agent Cost (today)"><div style={{ fontFamily: UI, fontSize: 11, color: '#808080' }}>Failed to load /dashboard/agent-costs.</div></Panel>
  }

  const rows = costs.today || []
  const total = rows.reduce((s, r) => s + (r.cost_usd || 0), 0)
  const maxCost = Math.max(...rows.map(r => r.cost_usd || 0), 0.0001)
  const mtd = costs.mtd_usd || 0
  const budget = costs.budget_usd || 150
  const day = new Date().getUTCDate() || 1
  const projection = (mtd / day) * 30
  const underBudget = projection <= budget
  const pctBudget = budget ? Math.round((mtd / budget) * 100) : 0

  return (
    <Panel title={`Per-Agent Cost (today) — $${total.toFixed(2)} total`} style={{ minHeight: 0 }}>
      {rows.length === 0 && (
        <div style={{ fontFamily: UI, fontSize: 11, color: '#808080' }}>No LLM usage logged today.</div>
      )}
      {rows.map(r => (
        <div key={r.caller} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '1px 0', fontSize: 11, fontFamily: MONO }}>
          <span style={{ width: 110, textAlign: 'right', fontFamily: UI, fontSize: 10, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', flexShrink: 0 }} title={r.caller}>
            {r.caller}
          </span>
          <BarMeter pct={((r.cost_usd || 0) / maxCost) * 100} color="#000080" height={12} />
          <span style={{ width: 58, textAlign: 'right', flexShrink: 0 }}>${(r.cost_usd || 0).toFixed(2)}</span>
          <span style={{ width: 52, textAlign: 'right', flexShrink: 0, color: '#808080', fontSize: 9 }}>{r.calls} calls</span>
        </div>
      ))}
      <div style={{ borderTop: '1px solid #808080', marginTop: 4, paddingTop: 3, fontFamily: UI, fontSize: 10, color: '#808080' }}>
        MTD ${mtd.toFixed(2)} of ${budget.toFixed(0)} budget ({pctBudget}%) · projection ${projection.toFixed(0)}{' '}
        <span style={{ color: underBudget ? GREEN : OLIVE, fontWeight: 'bold' }}>{underBudget ? '✓' : '⚠ over budget'}</span>
      </div>
    </Panel>
  )
}

// ── (d) Agent Message Bus ────────────────────────────────────

function MessageBusPanel({ bus }) {
  const msgs = bus?.messages || []
  return (
    <Panel title="Agent Message Bus — raw" bodyBg="#000" bodyPad={4} style={{ minHeight: 0 }}>
      <div style={{ fontFamily: MONO, fontSize: 10, lineHeight: 1.6 }}>
        {bus === undefined && <div style={{ color: '#606060' }}>Loading...</div>}
        {bus === null && <div style={{ color: '#606060' }}>Failed to load /dashboard/message-bus.</div>}
        {bus && msgs.length === 0 && <div style={{ color: '#606060' }}>No inter-agent messages recorded.</div>}
        {msgs.map((m, i) => (
          <div key={i} style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginBottom: 1, color: '#c0c0c0' }}>
            <span style={{ color: '#606060' }}>{fmtTimeET(m.timestamp)} </span>
            <span style={{ color: '#00c0c0' }}>{m.sender || '?'}</span>
            <span style={{ color: '#606060' }}>{'→'}</span>
            <span style={{ color: '#c000c0' }}>{m.recipient || 'broadcast'}</span>
            {' '}{m.message_type}{m.subject ? `/${m.subject}` : ''}
          </div>
        ))}
      </div>
    </Panel>
  )
}

// ── Sleeve Conflicts (7d) ────────────────────────────────────

function ConflictsPanel({ conflicts }) {
  const rows = conflicts?.conflicts || []
  return (
    <Panel title="Sleeve Conflicts (7d) — orchestrator resolution audit" style={{ minHeight: 120 }}>
      {conflicts === undefined && <div style={{ fontFamily: UI, fontSize: 11, color: '#808080' }}>Loading...</div>}
      {conflicts === null && <div style={{ fontFamily: UI, fontSize: 11, color: '#808080' }}>Failed to load /dashboard/conflicts.</div>}
      {conflicts && rows.length === 0 && (
        <div style={{ fontFamily: UI, fontSize: 11, color: '#808080' }}>
          No conflicts in the last 7 days — sleeves claimed distinct symbols.
        </div>
      )}
      {rows.map((c, i) => (
        <div key={i} style={{ borderBottom: i < rows.length - 1 ? '1px solid #c0c0c0' : 'none', padding: '4px 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: MONO, fontSize: 11 }}>
            <span style={{ color: '#808080', fontSize: 10 }}>{fmtTimeET(c.timestamp)}</span>
            <span style={{ fontWeight: 'bold' }}>{c.symbol || c.contested_symbol || '?'}</span>
            <ModeBadge mode={c.resolution_mode} />
            <span style={{ fontFamily: UI, fontSize: 10, color: '#808080' }}>winner</span>
            <span style={{ fontWeight: 'bold' }}>{c.winner || '--'}</span>
          </div>
          {(c.competitors || []).map((k, j) => (
            <div key={j} style={{ fontFamily: MONO, fontSize: 10, padding: '1px 0 0 16px', color: '#404040' }}>
              <span style={{ fontWeight: c.winner === k.sleeve_id ? 'bold' : 'normal' }}>{k.sleeve_id}</span>
              {k.estimated_edge != null && <span style={{ color: '#808080' }}> edge {k.estimated_edge}</span>}
              {k.one_liner && <span style={{ fontFamily: UI, color: '#606060' }}> — {k.one_liner}</span>}
            </div>
          ))}
          {c.verdict_text && (
            <div style={{ fontFamily: MONO, fontSize: 10, color: '#404040', padding: '2px 0 0 16px', whiteSpace: 'pre-wrap' }}>
              {c.verdict_text}
            </div>
          )}
        </div>
      ))}
    </Panel>
  )
}

// ── Page ─────────────────────────────────────────────────────

export default function AgentsPage() {
  // undefined = loading, null = fetch failed, object = data
  const [costs, setCosts] = useState(undefined)
  const [bus, setBus] = useState(undefined)
  const [conflicts, setConflicts] = useState(undefined)
  const [recon, setRecon] = useState(undefined)

  const loadBus = useCallback(() => {
    fetchMessageBus(30).then(setBus).catch(() => setBus(null))
  }, [])

  useEffect(() => {
    fetchAgentCosts().then(setCosts).catch(() => setCosts(null))
    fetchConflicts(7).then(setConflicts).catch(() => setConflicts(null))
    fetchReconciliation().then(setRecon).catch(() => setRecon(null))
    loadBus()
    const t = setInterval(loadBus, 15000) // message bus polls every 15s
    return () => clearInterval(t)
  }, [loadBus])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      <IntegrityStrip costs={costs} recon={recon} />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gridAutoRows: 'minmax(240px, auto)', gap: 4, padding: 4 }}>
        <WriteAuditPanel />
        <OverwritePanel />
        <CostPanel costs={costs} />
        <MessageBusPanel bus={bus} />
        <div style={{ gridColumn: '1 / -1', display: 'flex', flexDirection: 'column' }}>
          <ConflictsPanel conflicts={conflicts} />
        </div>
      </div>
    </div>
  )
}
