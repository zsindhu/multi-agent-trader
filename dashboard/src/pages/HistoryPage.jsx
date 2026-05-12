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

function fmtDateTime(iso) {
  if (!iso) return '--'
  const d = new Date(iso)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ' +
    d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
}

// ── Filter Bar Component ─────────────────────────────────────

function FilterBar({ children }) {
  return (
    <div style={{
      display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap',
      padding: '3px 4px', background: '#d4d0c8', borderBottom: '1px solid #808080',
      fontSize: 11, fontFamily: 'var(--w95-font-ui)',
    }}>
      {children}
    </div>
  )
}

function FilterSelect({ label, value, onChange, options }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
      <span style={{ color: '#000', fontSize: 10 }}>{label}:</span>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{
          border: '2px inset #dfdfdf', background: '#fff', fontFamily: 'var(--w95-font-mono)',
          fontSize: 11, padding: '1px 2px', borderRadius: 0,
        }}
      >
        {options.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </label>
  )
}

function FilterInput({ label, value, onChange, placeholder }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
      <span style={{ color: '#000', fontSize: 10 }}>{label}:</span>
      <input
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          border: '2px inset #dfdfdf', background: '#fff', fontFamily: 'var(--w95-font-mono)',
          fontSize: 11, padding: '1px 4px', width: 100, borderRadius: 0,
        }}
      />
    </label>
  )
}

function ClearButton({ onClick }) {
  return <button className="w95-btn" onClick={onClick} style={{ fontSize: 10, padding: '1px 6px' }}>Clear</button>
}

// ── Trade Summary Stats Bar ──────────────────────────────────

function TradeSummaryBar({ summary }) {
  if (!summary) return null
  const { total, wins, losses, win_rate, total_pnl, avg_pnl, avg_hold_days } = summary
  const pnlCls = total_pnl >= 0 ? 'w95-profit' : 'w95-loss'

  return (
    <div className="w95-stats">
      <div className="w95-stat"><span className="w95-stat-label">Total</span><span className="w95-stat-value">{total}</span></div>
      <div className="w95-stat"><span className="w95-stat-label">Win</span><span className="w95-stat-value w95-profit">{wins}</span></div>
      <div className="w95-stat"><span className="w95-stat-label">Loss</span><span className="w95-stat-value w95-loss">{losses}</span></div>
      <div className="w95-stat"><span className="w95-stat-label">Rate</span><span className="w95-stat-value">{win_rate}%</span></div>
      <div className="w95-stat"><span className="w95-stat-label">Avg PnL</span><span className={`w95-stat-value ${pnlCls}`}>{fmtDollar(avg_pnl)}</span></div>
      <div className="w95-stat"><span className="w95-stat-label">Total PnL</span><span className={`w95-stat-value ${pnlCls}`}>{fmtDollar(total_pnl)}</span></div>
      <div className="w95-stat"><span className="w95-stat-label">Avg Hold</span><span className="w95-stat-value">{avg_hold_days}d</span></div>
    </div>
  )
}

// ── Trades Table with Filtering ──────────────────────────────

function TradesPanel({ trades }) {
  const items = Array.isArray(trades) ? trades : []
  const [statusFilter, setStatusFilter] = useState('all')
  const [symbolSearch, setSymbolSearch] = useState('')
  const [funnelOnly, setFunnelOnly] = useState(false)

  if (trades === null) return <div className="w95-muted">Loading...</div>

  const filterButtons = [
    { value: 'all', label: 'All' },
    { value: 'open', label: 'Open' },
    { value: 'closed', label: 'Closed' },
    { value: 'won', label: 'Won' },
    { value: 'lost', label: 'Lost' },
  ]

  const filtered = items.filter(t => {
    const dOutcome = t.display_outcome || ''
    if (statusFilter === 'open') {
      if (dOutcome !== 'Open') return false
    } else if (statusFilter === 'closed') {
      if (!['Closed', 'Close', 'Expired', 'Assigned', 'Win', 'Loss', 'Breakeven'].includes(dOutcome)) return false
    } else if (statusFilter === 'won') {
      if (dOutcome !== 'Win' && !(t.display_pnl > 0)) return false
    } else if (statusFilter === 'lost') {
      if (dOutcome !== 'Loss' && !(t.display_pnl < 0)) return false
    }
    if (symbolSearch && !t.symbol?.toLowerCase().includes(symbolSearch.toLowerCase())) return false
    if (funnelOnly && !t.funnel_driven) return false
    return true
  })

  // Per-filter summary stats (recomputed from the currently filtered set)
  const filteredWithPnl = filtered.filter(t => t.display_pnl != null)
  const filteredWins = filtered.filter(t => t.display_outcome === 'Win' || (t.display_pnl > 0 && t.display_outcome !== 'Close')).length
  const filteredLosses = filtered.filter(t => t.display_outcome === 'Loss' || (t.display_pnl < 0 && t.display_outcome !== 'Close')).length
  const filteredPnl = filteredWithPnl.reduce((sum, t) => sum + t.display_pnl, 0)
  const filteredWinRate = filteredWins + filteredLosses > 0
    ? Math.round(filteredWins / (filteredWins + filteredLosses) * 100)
    : null

  return (
    <div>
      <FilterBar>
        {filterButtons.map(b => (
          <button
            key={b.value}
            className="w95-btn"
            style={statusFilter === b.value ? { borderStyle: 'inset', fontWeight: 'bold' } : {}}
            onClick={() => setStatusFilter(b.value)}
          >
            {b.label}
          </button>
        ))}
        <span style={{ width: 1, height: 16, background: '#808080', margin: '0 2px' }} />
        <FilterInput label="Symbol" value={symbolSearch} onChange={setSymbolSearch} placeholder="AAPL..." />
        <label style={{ display: 'flex', alignItems: 'center', gap: 3, fontSize: 10 }}>
          <input type="checkbox" checked={funnelOnly} onChange={e => setFunnelOnly(e.target.checked)} />
          Funnel only
        </label>
        {(statusFilter !== 'all' || symbolSearch || funnelOnly) &&
          <ClearButton onClick={() => { setStatusFilter('all'); setSymbolSearch(''); setFunnelOnly(false) }} />
        }
        <span className="w95-muted" style={{ marginLeft: 'auto', fontSize: 10 }}>{filtered.length}/{items.length}</span>
      </FilterBar>
      {filtered.length > 0 && (
        <div className="w95-stats" style={{ borderBottom: '1px solid #808080' }}>
          <div className="w95-stat"><span className="w95-stat-label">Count</span><span className="w95-stat-value">{filtered.length}</span></div>
          <div className="w95-stat"><span className="w95-stat-label">PnL</span><span className={`w95-stat-value ${filteredPnl >= 0 ? 'w95-profit' : 'w95-loss'}`}>{fmtDollar(filteredPnl)}</span></div>
          {filteredWinRate !== null && (
            <div className="w95-stat"><span className="w95-stat-label">Win Rate</span><span className="w95-stat-value">{filteredWinRate}%</span></div>
          )}
          <div className="w95-stat"><span className="w95-stat-label">Wins</span><span className="w95-stat-value w95-profit">{filteredWins}</span></div>
          <div className="w95-stat"><span className="w95-stat-label">Losses</span><span className="w95-stat-value w95-loss">{filteredLosses}</span></div>
        </div>
      )}
      {filtered.length === 0 ? (
        <div className="w95-muted" style={{ padding: 8 }}>No trades match filters</div>
      ) : (
        <div style={{ maxHeight: 300, overflow: 'auto' }}>
          <table className="w95-table">
            <thead>
              <tr>
                <th>Symbol</th><th>Type</th><th>Entry</th><th>Exit</th>
                <th>Premium</th><th>PnL ($)</th><th>PnL (%)</th>
                <th>Days</th><th>Outcome</th><th>Funnel</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((t, i) => {
                const pnl = t.display_pnl
                const pnlCls = pnl != null ? (pnl > 0 ? 'w95-profit' : pnl < 0 ? 'w95-loss' : '') : ''
                const outcomeCls = t.display_outcome === 'Win' ? 'w95-profit'
                  : t.display_outcome === 'Loss' ? 'w95-loss'
                  : t.display_outcome === 'Open' ? 'w95-muted' : ''
                return (
                  <tr key={i}>
                    <td className="w95-bold">{t.symbol}</td>
                    <td>{t.trade_type || '--'}</td>
                    <td>{fmtDate(t.created_at)}</td>
                    <td>{fmtDate(t.closed_at)}</td>
                    <td>{t.premium != null ? `$${Number(t.premium).toFixed(0)}` : '--'}</td>
                    <td className={pnlCls}>{pnl != null ? fmtDollar(pnl) : '--'}</td>
                    <td className={pnlCls}>{t.outcome_pnl_pct != null ? `${t.outcome_pnl_pct.toFixed(1)}%` : '--'}</td>
                    <td>{t.holding_days ?? '--'}</td>
                    <td className={outcomeCls}>{t.display_outcome}</td>
                    <td>{t.funnel_driven ? '\u2713' : ''}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Daily PnL Chart ──────────────────────────────────────────

function DailyPnLChart({ daily }) {
  const items = Array.isArray(daily) ? daily : []
  if (items.length === 0) return <div className="w95-muted">No data</div>

  const maxAbs = Math.max(...items.map(d => Math.abs(d.cumulative_pnl)), 1)

  return (
    <div>
      <div className="w95-chart" style={{ height: 100 }}>
        {items.filter((_, i) => i % Math.max(1, Math.floor(items.length / 60)) === 0).map((d, i) => {
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
  const items = Array.isArray(daily) ? daily : []
  if (items.length === 0) return <div className="w95-muted">No data</div>

  const maxPromos = Math.max(...items.map(d => d.promotions), 1)

  return (
    <div>
      <div className="w95-chart" style={{ height: 100 }}>
        {items.filter((_, i) => i % Math.max(1, Math.floor(items.length / 60)) === 0).map((d, i) => {
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

// ── Playbook Panel with Filtering ────────────────────────────

function PlaybookPanel({ entries, days }) {
  const allItems = Array.isArray(entries) ? entries : []
  const [catFilter, setCatFilter] = useState('all')
  const [search, setSearch] = useState('')

  if (entries === null) return <div className="w95-muted">Loading...</div>

  // Filter by lookback days
  const cutoff = days ? new Date(Date.now() - days * 86400000) : null
  const items = allItems.filter(e => {
    if (catFilter !== 'all' && (e.category || 'uncategorized') !== catFilter) return false
    if (search && !e.content?.toLowerCase().includes(search.toLowerCase())) return false
    if (cutoff && e.created_at && new Date(e.created_at) < cutoff) return false
    return true
  })

  const categories = [...new Set(allItems.map(e => e.category || 'uncategorized').filter(Boolean))]
  const catOpts = [{ value: 'all', label: 'All' }, ...categories.map(c => ({ value: c, label: c.replace(/_/g, ' ') }))]

  const catColors = {
    lesson_learned: '#800000', parameter_adjustment: '#000080', symbol_note: '#008000',
    regime_observation: '#808000', strategy_rule: '#800080', market_insight: '#008080',
  }

  return (
    <div>
      <FilterBar>
        <FilterSelect label="Category" value={catFilter} onChange={setCatFilter} options={catOpts} />
        <FilterInput label="Search" value={search} onChange={setSearch} placeholder="keyword..." />
        {(catFilter !== 'all' || search) && <ClearButton onClick={() => { setCatFilter('all'); setSearch('') }} />}
        <span className="w95-muted" style={{ marginLeft: 'auto', fontSize: 10 }}>{items.length}/{allItems.length}</span>
      </FilterBar>
      {items.length === 0 ? (
        <div className="w95-muted" style={{ padding: 8 }}>No playbook entries match</div>
      ) : (
        <table className="w95-table">
          <thead><tr><th>Category</th><th>Content</th><th>Conf</th><th>Date</th></tr></thead>
          <tbody>
            {items.map((e, i) => (
              <tr key={i}>
                <td><span className="w95-badge" style={{ color: catColors[e.category] || '#000' }}>{e.category?.replace(/_/g, ' ')}</span></td>
                <td style={{ whiteSpace: 'normal', maxWidth: 400, fontSize: 11 }}>{e.content}</td>
                <td>{e.confidence != null ? e.confidence.toFixed(2) : '--'}</td>
                <td>{fmtDate(e.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ── Recent Cycles Panel with Filtering ───────────────────────

function CyclesPanel({ cycles }) {
  const [expandedId, setExpandedId] = useState(null)
  const allItems = Array.isArray(cycles) ? cycles : []
  const [sleeveFilter, setSleeveFilter] = useState('all')
  const [minCost, setMinCost] = useState('0')

  if (cycles === null) return <div className="w95-muted">Loading...</div>

  const minCostNum = parseFloat(minCost) || 0
  const items = allItems.filter(c => {
    if (sleeveFilter !== 'all' && !(c.summary || '').toLowerCase().includes(sleeveFilter)) return false
    if (minCostNum > 0 && (c.llm_cost_usd || 0) < minCostNum) return false
    return true
  })

  const sleeves = ['all', 'vol_reversion', 'event_driven', 'yield_farming', 'sector_rotation']
  const sleeveOpts = sleeves.map(s => ({ value: s, label: s === 'all' ? 'All' : s.replace(/_/g, ' ') }))

  const costOpts = [
    { value: '0', label: 'All' },
    { value: '0.01', label: '> $0.01' },
    { value: '0.10', label: '> $0.10' },
    { value: '1.00', label: '> $1.00' },
  ]

  return (
    <div>
      <FilterBar>
        <FilterSelect label="Sleeve" value={sleeveFilter} onChange={setSleeveFilter} options={sleeveOpts} />
        <FilterSelect label="Min cost" value={minCost} onChange={setMinCost} options={costOpts} />
        {(sleeveFilter !== 'all' || minCostNum > 0) &&
          <ClearButton onClick={() => { setSleeveFilter('all'); setMinCost('0') }} />
        }
        <span className="w95-muted" style={{ marginLeft: 'auto', fontSize: 10 }}>{items.length}/{allItems.length}</span>
      </FilterBar>
      {items.length === 0 ? (
        <div className="w95-muted" style={{ padding: 8 }}>No cycles match filters</div>
      ) : (
        <table className="w95-table">
          <thead><tr><th>ID</th><th>Time</th><th>Cost</th><th>Actions</th><th>Summary</th></tr></thead>
          <tbody>
            {items.map(c => (
              <>
                <tr
                  key={`c-${c.id}`}
                  className={`w95-row-click ${expandedId === c.id ? 'w95-row-expanded' : ''}`}
                  onClick={() => setExpandedId(expandedId === c.id ? null : c.id)}
                >
                  <td>{c.id}</td>
                  <td>{fmtDateTime(c.timestamp)}</td>
                  <td>${(c.llm_cost_usd || 0).toFixed(4)}</td>
                  <td>{c.actions_executed || 0}/{c.actions_decided || 0}</td>
                  <td style={{ maxWidth: 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'normal' }}>
                    {stripFences(c.summary || '--').slice(0, 200)}
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
      )}
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────

export default function HistoryPage() {
  const [trades, setTrades] = useState(null)
  const [summary, setSummary] = useState(null)
  const [daily, setDaily] = useState(null)
  const [playbook, setPlaybook] = useState(null)
  const [cycles, setCycles] = useState(null)
  const [days, setDays] = useState(90)

  const loadAll = useCallback(() => {
    fetchDashboardTrades(days).then(d => {
      setTrades(d?.trades || [])
      setSummary(d?.summary || null)
    }).catch(() => { setTrades([]); setSummary(null) })
    fetchDashboardDailyStats(days).then(d => setDaily(d?.daily || [])).catch(() => setDaily([]))
    fetchDashboardPlaybook(100).then(d => setPlaybook(d?.entries || [])).catch(() => setPlaybook([]))
    fetchDashboardCycles(100, days).then(d => setCycles(d?.cycles || [])).catch(() => setCycles([]))
  }, [days])

  useEffect(() => { loadAll() }, [loadAll])

  return (
    <div className="w95" style={{ minHeight: '100%' }}>
      <div className="w95-page">
        {/* Period selector */}
        <div style={{ display: 'flex', gap: 4, alignItems: 'center', padding: '2px 0' }}>
          <span style={{ fontSize: 11, fontWeight: 'bold' }}>Lookback:</span>
          {[7, 14, 30, 60, 90, 180, 365].map(d => (
            <button
              key={d}
              className="w95-btn"
              style={days === d ? { borderStyle: 'inset', fontWeight: 'bold' } : {}}
              onClick={() => setDays(d)}
            >
              {d}d
            </button>
          ))}
        </div>

        {/* Trade Summary */}
        <W95Window title="Trade Summary" icon="&#128176;">
          <TradesPanel trades={trades} />
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
          <W95Window title="Playbook" icon="&#128214;" maxHeight={400}>
            <PlaybookPanel entries={playbook} days={days} />
          </W95Window>

          <W95Window title="Recent Cycles" icon="&#128337;" maxHeight={400}>
            <CyclesPanel cycles={cycles} />
          </W95Window>
        </div>
      </div>
    </div>
  )
}
