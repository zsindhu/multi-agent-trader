import { useState, useEffect, useCallback } from 'react'
import '../win95.css'
import W95Window from '../components/W95Window'
import {
  fetchDashboardTrades,
  fetchDashboardDailyStats,
  fetchDashboardPlaybook,
  fetchDashboardCycles,
} from '../api'

// ── Helpers ──────────────────────────────────────────────────

function stripFences(text) {
  if (!text) return text
  return text
    .replace(/```json\s*/g, '')
    .replace(/```\s*/g, '')
    .trim()
}

function fmtDate(iso) {
  if (!iso) return '--'
  const d = new Date(iso)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function fmtShortDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr + 'T00:00:00')
  return `${d.getMonth() + 1}/${d.getDate()}`
}

function fmtDollar(n) {
  if (n == null) return '--'
  const s = n >= 0 ? '' : '-'
  return s + '$' + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function fmtTime(iso) {
  if (!iso) return '--:--'
  const d = new Date(iso)
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
}

// ── Trade Summary Stats Bar ──────────────────────────────────

function TradeSummaryBar({ summary }) {
  if (!summary) return null
  const { total, wins, losses, win_rate, total_pnl, avg_pnl, avg_hold_days } = summary
  const pnlCls = total_pnl >= 0 ? 'w95-profit' : 'w95-loss'

  return (
    <div className="w95-stats">
      <div className="w95-stat">
        <span className="w95-stat-label">Total</span>
        <span className="w95-stat-value">{total}</span>
      </div>
      <div className="w95-stat">
        <span className="w95-stat-label">Win</span>
        <span className="w95-stat-value w95-profit">{wins}</span>
      </div>
      <div className="w95-stat">
        <span className="w95-stat-label">Loss</span>
        <span className="w95-stat-value w95-loss">{losses}</span>
      </div>
      <div className="w95-stat">
        <span className="w95-stat-label">Rate</span>
        <span className="w95-stat-value">{win_rate}%</span>
      </div>
      <div className="w95-stat">
        <span className="w95-stat-label">Avg PnL</span>
        <span className={`w95-stat-value ${pnlCls}`}>{fmtDollar(avg_pnl)}</span>
      </div>
      <div className="w95-stat">
        <span className="w95-stat-label">Total PnL</span>
        <span className={`w95-stat-value ${pnlCls}`}>{fmtDollar(total_pnl)}</span>
      </div>
      <div className="w95-stat">
        <span className="w95-stat-label">Avg Hold</span>
        <span className="w95-stat-value">{avg_hold_days}d</span>
      </div>
    </div>
  )
}

// ── Trades Table ─────────────────────────────────────────────

function TradesTable({ trades }) {
  if (!trades) return <div className="w95-muted">Loading...</div>
  if (trades.length === 0) return <div className="w95-muted">No trades in this period</div>

  return (
    <table className="w95-table">
      <thead>
        <tr>
          <th>Symbol</th>
          <th>Type</th>
          <th>Entry</th>
          <th>Exit</th>
          <th>Premium</th>
          <th>PnL ($)</th>
          <th>PnL (%)</th>
          <th>Days</th>
          <th>Outcome</th>
          <th>Funnel</th>
        </tr>
      </thead>
      <tbody>
        {trades.map((t, i) => {
          const pnl = t.outcome_pnl
          const pnlCls = t.outcome === 'win' ? 'w95-profit' : t.outcome === 'loss' ? 'w95-loss' : ''
          return (
            <tr key={i}>
              <td className="w95-bold">{t.symbol}</td>
              <td>{t.trade_type || '--'}</td>
              <td>{fmtDate(t.created_at)}</td>
              <td>{fmtDate(t.closed_at)}</td>
              <td>{t.premium != null ? `$${Number(t.premium).toFixed(0)}` : '--'}</td>
              <td className={pnlCls}>{pnl != null ? fmtDollar(pnl) : '--'}</td>
              <td className={pnlCls}>{t.outcome_pnl_pct != null ? `${(t.outcome_pnl_pct * 100).toFixed(1)}%` : '--'}</td>
              <td>{t.holding_days ?? '--'}</td>
              <td className={pnlCls}>{t.outcome || t.status}</td>
              <td>{t.funnel_driven ? '\u2713' : ''}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// ── Daily PnL Chart ──────────────────────────────────────────

function DailyPnLChart({ daily }) {
  if (!daily || daily.length === 0) return <div className="w95-muted">No data</div>

  // Filter to days with trades or equity data
  const withData = daily.filter(d => d.trades > 0 || d.equity)
  if (withData.length === 0) {
    // Show cumulative PnL anyway
    const maxAbs = Math.max(...daily.map(d => Math.abs(d.cumulative_pnl)), 1)

    return (
      <div>
        <div className="w95-chart" style={{ height: 100 }}>
          {daily.filter((_, i) => i % Math.max(1, Math.floor(daily.length / 60)) === 0).map((d, i) => {
            const h = Math.abs(d.cumulative_pnl) / maxAbs * 80
            const cls = d.cumulative_pnl >= 0 ? 'positive' : 'negative'
            return (
              <div key={i} className="w95-chart-bar" title={`${d.date}: ${fmtDollar(d.cumulative_pnl)}`}>
                <div className={`w95-chart-bar-inner ${cls}`} style={{ height: `${Math.max(h, 1)}%` }} />
              </div>
            )
          })}
        </div>
        <div className="w95-muted" style={{ fontSize: 10, marginTop: 2, textAlign: 'center' }}>
          Cumulative PnL
        </div>
      </div>
    )
  }

  const maxAbs = Math.max(...daily.map(d => Math.abs(d.cumulative_pnl)), 1)

  return (
    <div>
      <div className="w95-chart" style={{ height: 100 }}>
        {daily.filter((_, i) => i % Math.max(1, Math.floor(daily.length / 60)) === 0).map((d, i) => {
          const h = Math.abs(d.cumulative_pnl) / maxAbs * 80
          const cls = d.cumulative_pnl >= 0 ? 'positive' : 'negative'
          return (
            <div key={i} className="w95-chart-bar" title={`${d.date}: ${fmtDollar(d.cumulative_pnl)}`}>
              <div className={`w95-chart-bar-inner ${cls}`} style={{ height: `${Math.max(h, 1)}%` }} />
            </div>
          )
        })}
      </div>
      <div className="w95-muted" style={{ fontSize: 10, marginTop: 2, textAlign: 'center' }}>
        Cumulative PnL &mdash; hover for values
      </div>
    </div>
  )
}

// ── Promotions Over Time Chart ───────────────────────────────

function PromotionsChart({ daily }) {
  if (!daily || daily.length === 0) return <div className="w95-muted">No data</div>

  const maxPromos = Math.max(...daily.map(d => d.promotions), 1)

  return (
    <div>
      <div className="w95-chart" style={{ height: 100 }}>
        {daily.filter((_, i) => i % Math.max(1, Math.floor(daily.length / 60)) === 0).map((d, i) => {
          const h = (d.promotions / maxPromos) * 80
          return (
            <div key={i} className="w95-chart-bar" title={`${d.date}: ${d.promotions} promotions`}>
              <div className="w95-chart-bar-inner neutral" style={{ height: `${Math.max(h, d.promotions > 0 ? 2 : 0)}%` }} />
            </div>
          )
        })}
      </div>
      <div className="w95-muted" style={{ fontSize: 10, marginTop: 2, textAlign: 'center' }}>
        Daily Tier 2 promotions &mdash; hover for counts
      </div>
    </div>
  )
}

// ── Playbook Panel ───────────────────────────────────────────

function PlaybookPanel({ entries }) {
  if (!entries) return <div className="w95-muted">Loading...</div>
  if (entries.length === 0) return <div className="w95-muted">No playbook entries</div>

  const catColors = {
    lesson_learned: '#800000',
    parameter_adjustment: '#000080',
    symbol_note: '#008000',
    regime_observation: '#808000',
    strategy_rule: '#800080',
    market_insight: '#008080',
  }

  return (
    <table className="w95-table">
      <thead>
        <tr>
          <th>Category</th>
          <th>Content</th>
          <th>Conf</th>
          <th>Date</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((e, i) => (
          <tr key={i}>
            <td>
              <span className="w95-badge" style={{ color: catColors[e.category] || '#000' }}>
                {e.category?.replace(/_/g, ' ')}
              </span>
            </td>
            <td style={{ whiteSpace: 'normal', maxWidth: 400, fontSize: 11 }}>{e.content}</td>
            <td>{e.confidence != null ? e.confidence.toFixed(2) : '--'}</td>
            <td>{fmtDate(e.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ── Recent Cycles Panel ──────────────────────────────────────

function CyclesPanel({ cycles }) {
  const [expandedId, setExpandedId] = useState(null)

  if (!cycles) return <div className="w95-muted">Loading...</div>
  if (cycles.length === 0) return <div className="w95-muted">No cycles recorded</div>

  return (
    <table className="w95-table">
      <thead>
        <tr>
          <th>ID</th>
          <th>Time</th>
          <th>Cost</th>
          <th>Actions</th>
          <th>Summary</th>
        </tr>
      </thead>
      <tbody>
        {cycles.map(c => (
          <>
            <tr
              key={`c-${c.id}`}
              className={`w95-row-click ${expandedId === c.id ? 'w95-row-expanded' : ''}`}
              onClick={() => setExpandedId(expandedId === c.id ? null : c.id)}
            >
              <td>{c.id}</td>
              <td>{fmtTime(c.timestamp)}</td>
              <td>${(c.llm_cost_usd || 0).toFixed(4)}</td>
              <td>{c.actions_executed || 0}/{c.actions_decided || 0}</td>
              <td style={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {stripFences(c.summary || '--').slice(0, 100)}
              </td>
            </tr>
            {expandedId === c.id && (
              <tr key={`ce-${c.id}`} className="w95-expand">
                <td colSpan={5}>
                  <div style={{ marginBottom: 6 }}>
                    <span className="w95-bold">Regime:</span> {c.regime || '--'} |{' '}
                    <span className="w95-bold">VIX:</span> {c.vix_level || '--'} |{' '}
                    <span className="w95-bold">Equity:</span> {c.equity ? fmtDollar(c.equity) : '--'} |{' '}
                    <span className="w95-bold">Model:</span> {c.llm_model || '--'} |{' '}
                    <span className="w95-bold">Tokens:</span> {(c.llm_tokens_in || 0).toLocaleString()} in / {(c.llm_tokens_out || 0).toLocaleString()} out
                  </div>
                  <div className="w95-text-scroll" style={{ maxHeight: 200, fontSize: 11 }}>
                    {stripFences(c.reasoning) || '(no reasoning recorded)'}
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

// ── Main Page ────────────────────────────────────────────────

export default function HistoryPage() {
  const [trades, setTrades] = useState(null)
  const [summary, setSummary] = useState(null)
  const [daily, setDaily] = useState(null)
  const [playbook, setPlaybook] = useState(null)
  const [cycles, setCycles] = useState(null)
  const [days, setDays] = useState(30)

  const loadAll = useCallback(() => {
    fetchDashboardTrades(days).then(d => {
      setTrades(d.trades)
      setSummary(d.summary)
    }).catch(() => {})
    fetchDashboardDailyStats(days).then(d => setDaily(d.daily)).catch(() => {})
    fetchDashboardPlaybook().then(d => setPlaybook(d.entries)).catch(() => {})
    fetchDashboardCycles().then(d => setCycles(d.cycles)).catch(() => {})
  }, [days])

  useEffect(() => { loadAll() }, [loadAll])

  return (
    <div className="w95" style={{ minHeight: '100%' }}>
      <div className="w95-page">
        {/* Period selector */}
        <div style={{ display: 'flex', gap: 4, alignItems: 'center', padding: '2px 0' }}>
          <span style={{ fontSize: 11, fontWeight: 'bold' }}>Lookback:</span>
          {[7, 14, 30, 60, 90, 180].map(d => (
            <button
              key={d}
              className={`w95-btn ${days === d ? 'w95-bold' : ''}`}
              style={days === d ? { borderStyle: 'inset' } : {}}
              onClick={() => setDays(d)}
            >
              {d}d
            </button>
          ))}
        </div>

        {/* Trade Summary */}
        <W95Window title="Trade Summary" icon="&#128176;">
          <TradeSummaryBar summary={summary} />
          <div style={{ maxHeight: 300, overflow: 'auto', marginTop: 4 }}>
            <TradesTable trades={trades} />
          </div>
        </W95Window>

        {/* Charts row */}
        <div className="w95-grid w95-grid-2">
          <W95Window title="Daily PnL" icon="&#128200;">
            <DailyPnLChart daily={daily} />
          </W95Window>

          <W95Window title="Promotions Over Time" icon="&#128202;">
            <PromotionsChart daily={daily} />
          </W95Window>
        </div>

        {/* Playbook + Cycles */}
        <div className="w95-grid w95-grid-2">
          <W95Window title="Playbook" icon="&#128214;" maxHeight={320}>
            <PlaybookPanel entries={playbook} />
          </W95Window>

          <W95Window title="Recent Cycles" icon="&#128337;" maxHeight={320}>
            <CyclesPanel cycles={cycles} />
          </W95Window>
        </div>
      </div>
    </div>
  )
}
