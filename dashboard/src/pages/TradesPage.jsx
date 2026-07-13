/**
 * Trades & Learning (design 3b) — learning banner, filterable labeled trade
 * history with 3-state FUNNEL column, cycle judgments (envelope cards, 4a),
 * sleeve scorecard, Alpaca reconciliation, daily P&L, reflection (4d).
 * All data real; honest '--' / empty states where the API has no answer.
 */
import { useState, useEffect } from 'react'
import Panel from '../components/Panel'
import EnvelopeCard from '../components/EnvelopeCard'
import ReflectionCard from '../components/ReflectionCard'
import { SleeveBadge, SegmentedProgress, StatBox } from '../components/bits'
import { MONO, UI, sleeveInfo, fmtMoney, pnlColor, fmtTimeET } from '../lib/design'
import {
  fetchDashboardStatus,
  fetchDashboardTrades,
  fetchDashboardCycles,
  fetchDashboardDailyStats,
  fetchReconciliation,
} from '../api'

// ── helpers ──────────────────────────────────────────────────

const TH = {
  background: '#000080', color: '#fff', fontFamily: UI, fontSize: 11,
  padding: '2px 6px', textAlign: 'left', border: '1px solid #808080', whiteSpace: 'nowrap',
}
const TD = { padding: '2px 6px', border: '1px solid #c0c0c0' }
const MUTED = { fontFamily: UI, fontSize: 10, color: '#808080' }
const INPUT = { border: '2px inset #dfdfdf', background: '#fff', fontFamily: MONO, fontSize: 11, padding: '1px 4px' }
const BUTTON = { border: '2px outset #dfdfdf', background: '#c0c0c0', fontFamily: UI, fontSize: 10, padding: '1px 8px', cursor: 'pointer' }

function fmtDate(iso) {
  if (!iso) return '--'
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function exitReason(t) {
  // Derived from status only — the trades API carries no notes field.
  if (t.display_outcome === 'Unfilled') return 'order expired unfilled'
  if (t.status === 'expired') return 'expired worthless'
  if (t.status === 'assigned') return 'assigned'
  if (t.trade_type === 'buy_to_close') return 'bought to close'
  if (t.outcome && t.status === 'closed') return 'closed before expiry'
  return '--'
}

function rowTooltip(t) {
  if (t.premium == null || t.fill_price == null) return undefined
  const slip = Number(t.fill_price) - Number(t.premium)
  return `limit $${Number(t.premium).toFixed(2)} · fill $${Number(t.fill_price).toFixed(2)} · slippage $${slip.toFixed(2)}`
}

function LabelCell({ outcome }) {
  if (outcome === 'Win') return <span style={{ color: '#008000', fontWeight: 'bold' }}>WIN</span>
  if (outcome === 'Loss') return <span style={{ color: '#ff0000', fontWeight: 'bold' }}>LOSS</span>
  if (outcome === 'Partial Fill') {
    return (
      <span style={{
        fontFamily: UI, fontSize: 9, padding: '0 4px', textTransform: 'uppercase',
        border: '1px solid #808000', background: '#fffff0', color: '#808000',
      }}>Partial Fill</span>
    )
  }
  if (outcome === 'Unfilled') return <span style={{ color: '#808080' }}>Unfilled</span>
  if (outcome === 'Open') return <span style={{ color: '#606060' }}>Open</span>
  return <span>{outcome || '--'}</span>
}

function FunnelCell({ value }) {
  if (value === true) return <span style={{ color: '#008000', fontWeight: 'bold' }}>{'✓'}</span>
  if (value === false) return null
  return (
    <span style={{ color: '#808080' }} title="post-cutover trade, no surviving observation evidence">?</span>
  )
}

// ── learning banner ──────────────────────────────────────────

function LearningBanner({ status, tradesData }) {
  const lp = status?.learning_progress
  const summary = tradesData?.summary
  const threshold = lp?.threshold || 50

  const rows = tradesData?.trades || []
  const avg = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null)
  const avgWin = avg(rows.filter((t) => t.outcome === 'win' && t.outcome_pnl != null).map((t) => t.outcome_pnl))
  const avgLoss = avg(rows.filter((t) => t.outcome === 'loss' && t.outcome_pnl != null).map((t) => t.outcome_pnl))
  const avgWinLoss = avgWin == null && avgLoss == null
    ? '--'
    : `${avgWin != null ? fmtMoney(avgWin) : '--'} / ${avgLoss != null ? fmtMoney(Math.abs(avgLoss)) : '--'}`

  return (
    <div style={{ background: '#d4d0c8', borderBottom: '2px outset #dfdfdf', padding: '6px 8px', display: 'flex', gap: 8, alignItems: 'stretch' }}>
      <div style={{ border: '2px outset #dfdfdf', background: '#c0c0c0', padding: '4px 10px', flex: 1 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, fontFamily: UI, marginBottom: 3 }}>
          <span style={{ textTransform: 'uppercase', letterSpacing: '0.5px', color: '#404040' }}>
            Clean decisions
          </span>
          <span style={{ fontFamily: MONO, fontWeight: 'bold', fontSize: 12 }}>
            {lp ? `${lp.clean} / ${threshold}` : '--'}
          </span>
        </div>
        <SegmentedProgress clean={lp?.clean || 0} unknown={lp?.unknown || 0} total={threshold} />
        <div style={{ fontSize: 9, fontFamily: UI, color: '#606060', marginTop: 2 }}>
          {summary
            ? `${summary.wins} wins · ${summary.losses} losses · activates at ${threshold} clean`
            : '--'}
        </div>
      </div>
      <StatBox
        label="Win rate"
        value={summary ? `${summary.win_rate}%` : '--'}
        valueColor={summary && summary.win_rate > 50 ? '#008000' : '#000'}
      />
      <StatBox
        label="Realized P&L"
        value={summary ? fmtMoney(summary.total_pnl, { sign: true }) : '--'}
        valueColor={summary ? pnlColor(summary.total_pnl) : '#000'}
      />
      <StatBox label="Avg win / loss" value={avgWinLoss} />
    </div>
  )
}

// ── trade history ────────────────────────────────────────────

const OUTCOME_OPTIONS = ['All', 'Win', 'Loss', 'Open', 'Unfilled']

function TradeHistoryPanel({ tradesData }) {
  const [sleeve, setSleeve] = useState('All')
  const [outcome, setOutcome] = useState('All')
  const [symbol, setSymbol] = useState('')
  const [funnelOnly, setFunnelOnly] = useState(false)

  const rows = tradesData?.trades || []
  const sleeveOptions = ['All', ...Object.keys(tradesData?.summary?.by_sleeve || {})]

  const filtered = rows.filter((t) => {
    if (sleeve !== 'All' && (t.sleeve_id ?? t.trade_sleeve_id ?? 'unattributed') !== sleeve) return false
    if (outcome !== 'All' && t.display_outcome !== outcome) return false
    if (symbol && !(t.symbol || '').toUpperCase().includes(symbol.toUpperCase())) return false
    if (funnelOnly && t.funnel_driven !== true) return false // excludes null AND false
    return true
  })

  const closed = rows.filter((t) => ['Win', 'Loss', 'Breakeven', 'Closed'].includes(t.display_outcome)).length
  const open = rows.filter((t) => t.display_outcome === 'Open').length
  const title = tradesData ? `Trade History — ${closed} closed, ${open} open` : 'Trade History'

  const clear = () => { setSleeve('All'); setOutcome('All'); setSymbol(''); setFunnelOnly(false) }

  return (
    <Panel title={title} right={<span style={{ color: '#a0a0ff' }}>{tradesData ? `${filtered.length} SHOWN` : ''}</span>} bodyPad={0} style={{ maxHeight: 520 }}>
      <div style={{
        display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', padding: '3px 4px',
        background: '#d4d0c8', borderBottom: '1px solid #808080', fontSize: 10, fontFamily: UI,
        position: 'sticky', top: 0,
      }}>
        <label>Sleeve:{' '}
          <select style={INPUT} value={sleeve} onChange={(e) => setSleeve(e.target.value)}>
            {sleeveOptions.map((s) => (
              <option key={s} value={s}>{s === 'All' ? 'All' : sleeveInfo(s).name}</option>
            ))}
          </select>
        </label>
        <label>Outcome:{' '}
          <select style={INPUT} value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            {OUTCOME_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </label>
        <label>Symbol:{' '}
          <input style={{ ...INPUT, width: 70 }} value={symbol} placeholder="filter…" onChange={(e) => setSymbol(e.target.value)} />
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
          <input type="checkbox" checked={funnelOnly} onChange={(e) => setFunnelOnly(e.target.checked)} />
          funnel-only
        </label>
        <button style={BUTTON} onClick={clear}>Clear</button>
      </div>

      {tradesData == null && <div style={{ ...MUTED, padding: 6 }}>Loading…</div>}
      {tradesData != null && rows.length === 0 && (
        <div style={{ ...MUTED, padding: 6 }}>No trades in the last 90 days.</div>
      )}
      {tradesData != null && rows.length > 0 && filtered.length === 0 && (
        <div style={{ ...MUTED, padding: 6 }}>No trades match the current filters.</div>
      )}
      {filtered.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: MONO }}>
          <thead>
            <tr>
              <th style={TH}>CLOSED</th>
              <th style={TH}>SYMBOL</th>
              <th style={TH}>SLEEVE</th>
              <th style={TH}>TYPE</th>
              <th style={{ ...TH, textAlign: 'right' }}>STRIKE</th>
              <th style={{ ...TH, textAlign: 'right' }}>P&L</th>
              <th style={TH}>LABEL</th>
              <th style={TH}>FUNNEL</th>
              <th style={TH}>EXIT REASON</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((t, i) => {
              const sid = t.sleeve_id ?? t.trade_sleeve_id
              return (
                <tr key={t.id ?? i} title={rowTooltip(t)} style={{ background: i % 2 ? '#f0f0f0' : '#fff' }}>
                  <td style={TD}>{t.closed_at ? fmtDate(t.closed_at) : '--'}</td>
                  <td style={{ ...TD, fontWeight: 'bold' }}>{t.symbol}</td>
                  <td style={TD}>{sid ? <SleeveBadge id={sid} /> : '--'}</td>
                  <td style={TD}>{t.trade_type || '--'}</td>
                  <td style={{ ...TD, textAlign: 'right' }}>{t.strike ?? '--'}</td>
                  <td style={{ ...TD, textAlign: 'right', fontWeight: 'bold', color: pnlColor(t.display_pnl) }}>
                    {t.display_pnl != null ? fmtMoney(t.display_pnl, { sign: true }) : '--'}
                  </td>
                  <td style={TD}><LabelCell outcome={t.display_outcome} /></td>
                  <td style={{ ...TD, textAlign: 'center' }}><FunnelCell value={t.funnel_driven} /></td>
                  <td style={{ ...TD, fontSize: 10, color: '#404040' }}>{exitReason(t)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </Panel>
  )
}

// ── right rail ───────────────────────────────────────────────

function SleeveScorecardPanel({ tradesData }) {
  const bySleeve = tradesData?.summary?.by_sleeve || {}
  const entries = Object.entries(bySleeve)
  const SUB_TH = { background: '#d4d0c8', color: '#000', fontFamily: UI, fontSize: 9, padding: '1px 4px', textAlign: 'left', border: '1px solid #c0c0c0' }
  const SUB_TD = { padding: '1px 4px', border: '1px solid #e0e0e0' }
  return (
    <Panel title="Sleeve Scorecard" bodyPad={2}>
      {tradesData == null && <div style={MUTED}>Loading…</div>}
      {tradesData != null && entries.length === 0 && (
        <div style={{ ...MUTED, padding: 4 }}>No labeled outcomes yet.</div>
      )}
      {entries.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10, fontFamily: MONO }}>
          <thead>
            <tr>
              <th style={SUB_TH}>SLEEVE</th>
              <th style={{ ...SUB_TH, textAlign: 'right' }}>TRADES</th>
              <th style={{ ...SUB_TH, textAlign: 'right' }}>WIN%</th>
              <th style={{ ...SUB_TH, textAlign: 'right' }}>P&L</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([sid, s]) => (
              <tr key={sid}>
                <td style={{ ...SUB_TD, fontFamily: UI, fontSize: 10 }}>{sleeveInfo(sid).name}</td>
                <td style={{ ...SUB_TD, textAlign: 'right' }}>{s.trades}</td>
                <td style={{ ...SUB_TD, textAlign: 'right' }}>{s.win_rate != null ? `${s.win_rate}%` : '--'}</td>
                <td style={{ ...SUB_TD, textAlign: 'right', fontWeight: 'bold', color: pnlColor(s.pnl) }}>
                  {fmtMoney(s.pnl, { sign: true })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  )
}

function discrepancyHeadline(d) {
  const kind = (d.kind || 'discrepancy').replace(/_/g, ' ').toUpperCase()
  const sym = d.option_symbol || d.symbol || ''
  return `⚠ DISCREPANCY — ${kind}${sym ? ` ${sym}` : ''}`
}

function discrepancyText(d) {
  if (d.kind === 'fill_price_mismatch') {
    return `Broker filled at $${d.broker_fill} but DB recorded $${d.db_price}${d.trade_id != null ? ` (trade #${d.trade_id})` : ''}.`
  }
  if (d.kind === 'unintended_long_option') {
    return `Broker shows a long option position (${d.qty} contract${d.qty === 1 ? '' : 's'}) — the system only sells premium.`
  }
  return Object.entries(d).filter(([k]) => k !== 'kind').map(([k, v]) => `${k}=${v}`).join(' · ')
}

function ReconciliationPanel({ recon }) {
  const Row = ({ label, children }) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '1px 0' }}>
      <span style={{ fontFamily: UI, color: '#808080', fontSize: 10 }}>{label}</span>
      <span>{children}</span>
    </div>
  )
  const footer = (
    <div style={{ borderTop: '1px solid #808080', marginTop: 6, paddingTop: 4, fontFamily: UI, fontSize: 10, color: '#808080' }}>
      Nightly at 17:45 ET
    </div>
  )

  let right = null
  let body
  if (recon === undefined) {
    body = <div style={MUTED}>Loading…</div>
  } else if (recon === null) {
    body = (
      <div style={{ ...MUTED, lineHeight: 1.5 }}>
        No reconciliation report yet — the nightly DB-vs-Alpaca cross-check has not run.
      </div>
    )
  } else {
    const issues = recon.discrepancy_count || 0
    right = issues > 0
      ? <span style={{ color: '#ffff80' }}>{issues} ISSUE{issues === 1 ? '' : 'S'}</span>
      : <span style={{ color: '#80ff80' }}>OK</span>
    const matched = Math.max(0, (recon.orders_checked || 0) - issues)
    const firstDisc = (recon.discrepancies || [])[0]
    body = (
      <>
        <Row label="Last sync">{recon.ran_at ? `${fmtTimeET(recon.ran_at)} ET` : '--'}</Row>
        <Row label="Positions matched">
          <span style={{ color: issues === 0 ? '#008000' : '#808000', fontWeight: 'bold' }}>
            {matched} / {recon.orders_checked ?? '--'}
          </span>
        </Row>
        <Row label="Broker realized P&L">{fmtMoney(recon.broker_realized_pnl, { dp: 2 })}</Row>
        <Row label="DB labeled P&L">{fmtMoney(recon.labeled_outcome_pnl, { dp: 2 })}</Row>
        <Row label="Drift">
          <span style={{ color: '#808000', fontWeight: 'bold' }}>{fmtMoney(recon.pnl_drift, { dp: 2 })}</span>
        </Row>
        {firstDisc && (
          <div style={{ border: '1px solid #808000', background: '#fffff0', padding: '4px 6px', marginTop: 4, fontSize: 10, lineHeight: 1.5 }}>
            <div style={{ fontWeight: 'bold', color: '#808000' }}>{discrepancyHeadline(firstDisc)}</div>
            <div style={{ fontFamily: UI }}>{discrepancyText(firstDisc)}</div>
            {(recon.discrepancies || []).length > 1 && (
              <div style={{ fontFamily: UI, color: '#808080', marginTop: 2 }}>
                + {recon.discrepancies.length - 1} more in the nightly report
              </div>
            )}
          </div>
        )}
      </>
    )
  }

  return (
    <Panel title="Alpaca Reconciliation" right={right} bodyPad="4px 6px" bodyStyle={{ fontFamily: MONO, fontSize: 11 }}>
      {body}
      {footer}
    </Panel>
  )
}

function DailyPnlPanel({ daily }) {
  let body
  if (daily == null) {
    body = <div style={MUTED}>Loading…</div>
  } else if (daily.length === 0) {
    body = <div style={MUTED}>No daily stats available.</div>
  } else {
    const max = Math.max(...daily.map((d) => Math.abs(d.pnl || 0)), 1)
    const allZero = daily.every((d) => !d.pnl)
    body = (
      <>
        <div style={{ height: 80, display: 'flex', gap: 1, position: 'relative' }}>
          <div style={{ position: 'absolute', left: 0, right: 0, top: '50%', height: 1, background: '#c0c0c0' }} />
          {daily.map((d) => {
            const pnl = d.pnl || 0
            const up = pnl >= 0
            const pct = (Math.abs(pnl) / max) * 48
            return (
              <div key={d.date} title={`${d.date}: ${fmtMoney(d.pnl, { sign: true })}`} style={{ flex: 1, position: 'relative' }}>
                {pnl !== 0 && (
                  <div style={{
                    position: 'absolute', left: 0, right: 0,
                    [up ? 'bottom' : 'top']: '50%', height: `${Math.max(pct, 2)}%`,
                    background: up ? '#008000' : '#ff0000',
                  }} />
                )}
              </div>
            )
          })}
        </div>
        {allZero && (
          <div style={{ ...MUTED, marginTop: 3 }}>No labeled P&L in the last 30 days.</div>
        )}
      </>
    )
  }
  return <Panel title="Daily P&L (30d)" bodyPad={4}>{body}</Panel>
}

// ── page ─────────────────────────────────────────────────────

export default function TradesPage() {
  const [status, setStatus] = useState(null)
  const [tradesData, setTradesData] = useState(null)
  const [cycles, setCycles] = useState(null)
  const [recon, setRecon] = useState(undefined) // undefined = loading, null = no report
  const [daily, setDaily] = useState(null)

  useEffect(() => {
    fetchDashboardStatus().then(setStatus).catch(() => {})
    fetchDashboardTrades(90).then(setTradesData).catch(() => setTradesData({ trades: [], summary: null }))
    fetchDashboardCycles(6).then((d) => setCycles(d?.cycles || [])).catch(() => setCycles([]))
    fetchReconciliation().then((d) => setRecon(d?.report ?? null)).catch(() => setRecon(null))
    fetchDashboardDailyStats(30).then((d) => setDaily(d?.daily || [])).catch(() => setDaily([]))
  }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      <LearningBanner status={status} tradesData={tradesData} />

      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 330px', gap: 4, padding: 4, minHeight: 0, alignItems: 'start' }}>
        {/* left column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minHeight: 0 }}>
          <TradeHistoryPanel tradesData={tradesData} />

          <div>
            <div style={{
              fontFamily: UI, fontSize: 10, fontWeight: 'bold', textTransform: 'uppercase',
              letterSpacing: '0.5px', color: '#404040', margin: '2px 0 3px 2px',
            }}>
              Cycle Judgments — last {cycles ? cycles.length : '--'} lead cycles
            </div>
            {cycles == null && <div style={{ ...MUTED, marginLeft: 2 }}>Loading…</div>}
            {cycles != null && cycles.length === 0 && (
              <div style={{ ...MUTED, marginLeft: 2 }}>No lead cycles recorded yet.</div>
            )}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {(cycles || []).map((c) => <EnvelopeCard key={c.id} cycle={c} />)}
            </div>
          </div>
        </div>

        {/* right rail */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minHeight: 0 }}>
          <SleeveScorecardPanel tradesData={tradesData} />
          <ReconciliationPanel recon={recon} />
          <DailyPnlPanel daily={daily} />
          <ReflectionCard />
        </div>
      </div>
    </div>
  )
}
