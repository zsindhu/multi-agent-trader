import { useState, useEffect, useCallback } from 'react'
import '../win95.css'
import W95Window from '../components/W95Window'
import {
  fetchDashboardStatus,
  fetchDashboardPromotions,
  fetchDashboardSignals,
  fetchDashboardReflection,
  fetchOptions,
  fetchPositionAlerts,
} from '../api'

// ── Helpers ──────────────────────────────────────────────────

function fmtTime(iso) {
  if (!iso) return '--:--'
  const d = new Date(iso)
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function fmtDate(iso) {
  if (!iso) return '--'
  const d = new Date(iso)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function fmtDollar(n) {
  if (n == null) return '--'
  return '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function fmtPct(n) {
  if (n == null) return '--'
  return (n >= 0 ? '+' : '') + n.toFixed(1) + '%'
}

function dteFromExp(exp) {
  if (!exp) return '--'
  const diff = Math.floor((new Date(exp) - new Date()) / 86400000)
  return diff >= 0 ? diff : 0
}

// ── System Status Panel ──────────────────────────────────────

function SystemStatusPanel({ status }) {
  if (!status) return <div className="w95-muted">Loading...</div>

  const { funnel, last_tier1_sweep, last_tier2_sweep, last_cycle, today_llm_cost, today_errors } = status

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11 }}>
      <div className="w95-stats" style={{ flexDirection: 'column', gap: 2 }}>
        <div className="w95-stat" style={{ justifyContent: 'space-between', width: '100%' }}>
          <span className="w95-stat-label">Last Tier 1</span>
          <span className="w95-stat-value">{fmtTime(last_tier1_sweep)}</span>
        </div>
        <div className="w95-stat" style={{ justifyContent: 'space-between', width: '100%' }}>
          <span className="w95-stat-label">Last Tier 2</span>
          <span className="w95-stat-value">{fmtTime(last_tier2_sweep)}</span>
        </div>
        <div className="w95-stat" style={{ justifyContent: 'space-between', width: '100%' }}>
          <span className="w95-stat-label">Last Cycle</span>
          <span className="w95-stat-value">
            {fmtTime(last_cycle?.timestamp)}
            {last_cycle?.cost != null && <span className="w95-muted"> (${last_cycle.cost.toFixed(4)})</span>}
          </span>
        </div>
        <div className="w95-stat" style={{ justifyContent: 'space-between', width: '100%' }} title="DB-tracked estimate. Check console.anthropic.com for billing ground truth.">
          <span className="w95-stat-label">LLM Cost Today</span>
          <span className="w95-stat-value">${(today_llm_cost || 0).toFixed(4)}<span className="w95-muted" style={{ fontSize: 9, marginLeft: 3 }}>*</span></span>
        </div>
        <div className="w95-stat" style={{ justifyContent: 'space-between', width: '100%' }}>
          <span className="w95-stat-label">Errors Today</span>
          <span className={`w95-stat-value ${today_errors > 0 ? 'w95-loss' : ''}`}>{today_errors}</span>
        </div>
      </div>

      <div style={{ borderTop: '1px solid #808080', paddingTop: 4, marginTop: 2 }}>
        <div style={{ fontWeight: 'bold', marginBottom: 2, fontFamily: 'var(--w95-font-ui)' }}>Funnel</div>
        <div className="w95-mono" style={{ fontSize: 11 }}>
          Universe {funnel.tier1_universe} {'\u2192'} T2 {funnel.tier2_promoted}
          <span className="w95-muted"> ({funnel.tier2_rejected} rej)</span>
        </div>
      </div>
    </div>
  )
}

// ── Position Alert Banner ────────────────────────────────────

function PositionAlertBanner({ alerts }) {
  if (!alerts || alerts.length === 0) return null
  const danger = alerts.filter(a => a.level === 'CRITICAL' || a.level === 'DANGER')
  if (danger.length === 0) return null

  const hasCritical = danger.some(a => a.level === 'CRITICAL')
  const bgColor = hasCritical ? '#c00' : '#c90'
  const textColor = hasCritical ? '#fff' : '#000'

  return (
    <div style={{
      background: bgColor, color: textColor, padding: '3px 8px',
      fontSize: 11, fontFamily: 'var(--w95-font-ui)', fontWeight: 'bold',
      borderBottom: '1px solid #808080',
    }}>
      {danger.map((a, i) => (
        <span key={i}>
          {i > 0 && ' | '}
          {a.level === 'CRITICAL' ? '\u26A0' : '\u26A0'} {a.symbol} {a.level === 'CRITICAL' ? 'BELOW' : 'within ' + a.distance_pct + '% of'} strike ${a.strike}
        </span>
      ))}
    </div>
  )
}

// ── Active Positions Panel ───────────────────────────────────

function PositionsPanel({ positions, alerts }) {
  if (!positions) return <div className="w95-muted">Loading...</div>
  const allItems = Array.isArray(positions) ? positions : []
  // Filter to only truly open positions (exclude closed/expired/assigned)
  const items = allItems.filter(p => !p.status || p.status === 'open' || p.quantity !== 0)
  if (items.length === 0) return <div className="w95-muted">No active positions</div>

  return (
    <>
    <PositionAlertBanner alerts={alerts} />
    <table className="w95-table">
      <thead>
        <tr>
          <th>Symbol</th>
          <th>Type</th>
          <th>Strike</th>
          <th>Exp</th>
          <th>Entry</th>
          <th>Current</th>
          <th>PnL</th>
          <th>DTE</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {items.map((p, i) => {
          const pnl = p.unrealized_pl ?? p.pnl
          const pnlCls = pnl > 0 ? 'w95-profit' : pnl < 0 ? 'w95-loss' : ''
          return (
            <tr key={i}>
              <td className="w95-bold">{p.symbol}</td>
              <td>{p.contract_type || p.side || '--'}</td>
              <td>{p.strike ?? '--'}</td>
              <td>{p.expiration ? fmtDate(p.expiration) : '--'}</td>
              <td>{p.avg_cost != null ? `$${Number(p.avg_cost).toFixed(2)}` : p.entry_price != null ? `$${Number(p.entry_price).toFixed(2)}` : '--'}</td>
              <td>{p.current_price != null ? `$${Number(p.current_price).toFixed(2)}` : '--'}</td>
              <td className={pnlCls}>{pnl != null ? fmtDollar(pnl) : '--'}</td>
              <td>{dteFromExp(p.expiration)}</td>
              <td>{p.assigned_to || p.side || '--'}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
    </>
  )
}

// ── Promotions Panel ─────────────────────────────────────────

function PromotionsPanel({ promotions }) {
  const [expandedIdx, setExpandedIdx] = useState(null)
  const items = Array.isArray(promotions) ? promotions : []

  if (!promotions) return <div className="w95-muted">Loading...</div>
  if (items.length === 0) return <div className="w95-muted">No promotions today</div>

  return (
    <table className="w95-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Symbol</th>
          <th>Score</th>
          <th>Fired</th>
          <th>Top Signals</th>
          <th>Amp</th>
          <th>Reasoning</th>
        </tr>
      </thead>
      <tbody>
        {items.slice(0, 20).map((p, i) => (
          <>
            <tr
              key={`row-${i}`}
              className={`w95-row-click ${expandedIdx === i ? 'w95-row-expanded' : ''}`}
              onClick={() => setExpandedIdx(expandedIdx === i ? null : i)}
            >
              <td>{i + 1}</td>
              <td className="w95-bold">{p.symbol}</td>
              <td>{(p.composite_score || 0).toFixed(4)}</td>
              <td>{p.signals_fired}</td>
              <td>{(p.firing_rules || []).slice(0, 3).join(', ')}</td>
              <td>{p.amplification !== 1.0 ? `${p.amplification.toFixed(1)}x` : ''}</td>
              <td style={{ maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {(p.reasoning || '--').slice(0, 80)}
              </td>
            </tr>
            {expandedIdx === i && (
              <tr key={`exp-${i}`} className="w95-expand">
                <td colSpan={7}>
                  <div className="w95-expand-signals">
                    {Object.entries(p.signals || {}).map(([name, sig]) => (
                      <div key={name} className={`w95-expand-signal ${sig.fired ? 'fired' : ''}`}>
                        <span className="w95-bold">{name}</span>:{' '}
                        {sig.raw != null ? Number(sig.raw).toFixed(3) : '--'}
                        {sig.z_score != null && <span className="w95-muted"> z={Number(sig.z_score).toFixed(2)}</span>}
                        {sig.fired && <span className="w95-profit"> FIRED</span>}
                      </div>
                    ))}
                  </div>
                  <div style={{ fontFamily: 'var(--w95-font-mono)', fontSize: 11 }}>
                    <span className="w95-bold">Full Reasoning:</span>{' '}
                    {p.reasoning || '(none)'}
                  </div>
                </td>
              </tr>
            )}
          </>
        ))}
      </tbody>
    </table>
  )
}

// ── Signal Fire Rates Panel ──────────────────────────────────

function SignalBarsPanel({ signals }) {
  const items = Array.isArray(signals) ? signals : []
  if (!signals) return <div className="w95-muted">Loading...</div>
  if (items.length === 0) return <div className="w95-muted">No signal data</div>

  const maxRate = Math.max(...items.map(s => s.rate), 1)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {items.map(s => (
        <div key={s.signal} className="w95-bar-container">
          <span className="w95-bar-label">{s.signal}</span>
          <div className="w95-bar-track">
            <div
              className="w95-bar-fill"
              style={{ width: `${(s.rate / maxRate) * 100}%` }}
            />
          </div>
          <span className="w95-bar-value">{s.rate.toFixed(0)}%</span>
        </div>
      ))}
    </div>
  )
}

// ── Reflection Panel ─────────────────────────────────────────

function ReflectionPanel({ reflection }) {
  if (!reflection) return <div className="w95-muted">Loading...</div>
  if (!reflection.body) return <div className="w95-muted">No reflection available</div>

  return (
    <div>
      <div style={{ marginBottom: 4, fontSize: 10 }} className="w95-muted">
        {reflection.is_today ? fmtTime(reflection.timestamp) : `${fmtDate(reflection.timestamp)} (yesterday)`}
      </div>
      <div className="w95-text-scroll" style={{ maxHeight: 260 }}>
        {reflection.body}
      </div>
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────

export default function CommandCenterPage() {
  const [status, setStatus] = useState(null)
  const [promotions, setPromotions] = useState(null)
  const [signals, setSignals] = useState(null)
  const [reflection, setReflection] = useState(null)
  const [positions, setPositions] = useState(null)
  const [positionAlerts, setPositionAlerts] = useState([])

  const loadAll = useCallback(() => {
    fetchDashboardStatus().then(setStatus).catch(() => {})
    fetchDashboardPromotions().then(d => setPromotions(d?.promotions || [])).catch(() => setPromotions([]))
    fetchDashboardSignals().then(d => setSignals(d?.signals || [])).catch(() => setSignals([]))
    fetchDashboardReflection().then(setReflection).catch(() => {})
    fetchOptions().then(d => setPositions(d?.options || [])).catch(() => setPositions([]))
    fetchPositionAlerts().then(d => setPositionAlerts(d?.alerts || [])).catch(() => setPositionAlerts([]))
  }, [])

  useEffect(() => {
    loadAll()
    const interval = setInterval(() => {
      // Only auto-refresh during US market hours (9:30-16:00 ET, weekdays)
      const now = new Date()
      const utcH = now.getUTCHours()
      const utcM = now.getUTCMinutes()
      const etMinutes = ((utcH - 4) * 60 + utcM + 1440) % 1440  // ET = UTC-4 (EDT)
      const day = now.getUTCDay()
      const isWeekday = day >= 1 && day <= 5
      const isMarketHours = etMinutes >= 570 && etMinutes <= 960  // 9:30=570, 16:00=960
      if (isWeekday && isMarketHours) loadAll()
    }, 60000)
    return () => clearInterval(interval)
  }, [loadAll])

  return (
    <div className="w95" style={{ minHeight: '100%' }}>
      <div className="w95-page">
        {/* Row 1: Status + Positions */}
        <div className="w95-grid w95-grid-sidebar">
          <W95Window title="System Status" icon="&#128187;">
            <SystemStatusPanel status={status} />
          </W95Window>

          <W95Window title="Active Positions" icon="&#128200;">
            <PositionsPanel positions={positions} alerts={positionAlerts} />
          </W95Window>
        </div>

        {/* Row 2: Promotions */}
        <W95Window title="Top 20 Promotions" icon="&#128270;">
          <PromotionsPanel promotions={promotions} />
        </W95Window>

        {/* Row 3: Signals + Reflection */}
        <div className="w95-grid w95-grid-2">
          <W95Window title="Signal Fire Rates (14d)" icon="&#128202;">
            <SignalBarsPanel signals={signals} />
          </W95Window>

          <W95Window title="Latest Reflection" icon="&#128214;">
            <ReflectionPanel reflection={reflection} />
          </W95Window>
        </div>
      </div>
    </div>
  )
}
