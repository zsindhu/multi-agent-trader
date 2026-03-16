import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  DollarSign, TrendingUp, Wallet, Star, RefreshCw, Bot, Crosshair,
} from 'lucide-react'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts'
import StatCard from '../components/StatCard'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Spinner from '../components/Spinner'
import ActivePositions from '../components/ActivePositions'
import {
  fetchPortfolioSummary, fetchPortfolio, refreshPortfolio,
  fetchAgentStatus, fetchPerformance, fetchAgentPerformance,
  fetchTradeHistory,
} from '../api'

const fmt = (n) =>
  n == null ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 })

const fmtPct = (n) =>
  n == null ? '—' : `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`

const AGENT_COLORS = {
  'Covered-Calls': '#6366f1',
  'Cash-Secured-Puts': '#10b981',
  'Wheel': '#ec4899',
  'Scanner': '#f59e0b',
  'Trade-Journal': '#0ea5e9',
}
const AGENT_BADGE = {
  'Covered-Calls': 'indigo',
  'Cash-Secured-Puts': 'green',
  'Wheel': 'pink',
  'Scanner': 'yellow',
  'Trade-Journal': 'blue',
}

export default function DashboardPage() {
  const [summary, setSummary] = useState(null)
  const [options, setOptions] = useState([])
  const [agentStatus, setAgentStatus] = useState(null)
  const [agentMetrics, setAgentMetrics] = useState({})
  const [trades, setTrades] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [equityRange, setEquityRange] = useState('1M')

  const load = async () => {
    try {
      const [s, full, status, perf, history] = await Promise.all([
        fetchPortfolioSummary(),
        fetchPortfolio(),
        fetchAgentStatus(),
        fetchPerformance(),
        fetchTradeHistory({ limit: 200 }),
      ])
      setSummary(s)
      setOptions(full.options || [])
      setAgentStatus(status)
      setTrades(history?.trades || [])

      // Fetch per-agent metrics
      const metrics = {}
      for (const w of (status.workers || [])) {
        try { metrics[w.name] = await fetchAgentPerformance(w.name, 30) }
        catch { metrics[w.name] = null }
      }
      setAgentMetrics(metrics)
    } catch (e) {
      console.error('Dashboard load failed:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])
  useEffect(() => {
    const handler = () => { setLoading(true); load() }
    window.addEventListener('trading-mode-changed', handler)
    return () => window.removeEventListener('trading-mode-changed', handler)
  }, [])

  const handleRefresh = async () => {
    setRefreshing(true)
    try { await refreshPortfolio(); await load() }
    finally { setRefreshing(false) }
  }

  if (loading) return <div className="flex items-center justify-center h-64"><Spinner /></div>

  const regime = summary?.regime || {}
  const risk = agentStatus?.risk || {}
  const workers = agentStatus?.workers || []

  const regimeColor =
    regime.regime === 'high_vol' ? 'red' :
    regime.regime === 'low_vol' ? 'green' : 'blue'

  const drawdownPct = (risk.current_drawdown || 0) * 100
  const maxDrawdownPct = (risk.max_drawdown_limit || 0.10) * 100

  const isEmpty = options.length === 0 && trades.length === 0

  // Build equity curve from trade history
  const equityData = buildEquityData(trades, summary?.equity || 0)
  const filteredEquity = filterEquityRange(equityData, equityRange)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Dashboard</h2>
          <p className="text-sm text-[#64748b]">
            {summary?.last_updated ? `Updated ${new Date(summary.last_updated).toLocaleString()}` : 'Loading...'}
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="flex items-center gap-2 px-4 py-2 bg-[#1e293b] hover:bg-[#334155] border border-[#334155] text-white text-sm rounded-lg transition-colors disabled:opacity-50"
        >
          <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Stat Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Portfolio Value" value={fmt(summary?.equity)} icon={DollarSign} />
        <StatCard label="Cash Available" value={fmt(summary?.cash)} icon={Wallet} />
        <StatCard
          label="Unrealized P&L"
          value={fmt(summary?.total_unrealized_pnl)}
          trend={summary?.total_unrealized_pnl > 0 ? 'up' : summary?.total_unrealized_pnl < 0 ? 'down' : null}
          icon={TrendingUp}
        />
        <StatCard
          label="Premium Collected"
          value={fmt(summary?.total_premium_collected)}
          trend="up"
          icon={Star}
        />
      </div>

      {/* Empty state CTA */}
      {isEmpty && (
        <Card>
          <div className="py-10 text-center space-y-4">
            <Crosshair size={40} className="mx-auto text-[#334155]" />
            <div>
              <h3 className="text-lg font-semibold text-white mb-1">No active positions yet</h3>
              <p className="text-sm text-[#64748b] max-w-sm mx-auto">
                Head to the Trade Desk to run your first scan and review trade proposals before anything executes.
              </p>
            </div>
            <Link
              to="/trade-desk"
              className="inline-flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg transition-colors"
            >
              <Crosshair size={14} /> Go to Trade Desk
            </Link>
          </div>
        </Card>
      )}

      {/* Equity Chart */}
      {filteredEquity.length > 1 && (
        <Card
          title="Portfolio Equity"
          action={
            <div className="flex gap-1">
              {['1W', '1M', '3M', '6M', 'ALL'].map(r => (
                <button
                  key={r}
                  onClick={() => setEquityRange(r)}
                  className={`px-2 py-0.5 text-xs rounded transition-colors ${
                    equityRange === r
                      ? 'bg-blue-600 text-white'
                      : 'text-[#64748b] hover:text-white'
                  }`}
                >
                  {r}
                </button>
              ))}
            </div>
          }
        >
          <ResponsiveContainer width="100%" height={160}>
            <AreaChart data={filteredEquity}>
              <defs>
                <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#64748b' }} tickLine={false} axisLine={false} />
              <YAxis
                tick={{ fontSize: 10, fill: '#64748b' }}
                tickLine={false}
                axisLine={false}
                tickFormatter={v => `$${(v / 1000).toFixed(0)}k`}
                width={45}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                labelStyle={{ color: '#94a3b8', fontSize: 11 }}
                formatter={v => [fmt(v), 'Equity']}
              />
              <Area
                type="monotone"
                dataKey="equity"
                stroke="#3b82f6"
                fill="url(#equityGrad)"
                strokeWidth={2}
                dot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </Card>
      )}

      {/* Risk Gauge */}
      <Card title="Risk Monitor" subtitle={`Drawdown: ${drawdownPct.toFixed(1)}% of ${maxDrawdownPct.toFixed(0)}% limit`}>
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-[#64748b]">
            <span>0%</span>
            <span>{maxDrawdownPct.toFixed(0)}% limit</span>
          </div>
          <div className="h-3 bg-[#0a0f1e] rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                drawdownPct > 7 ? 'bg-red-500' :
                drawdownPct > 4 ? 'bg-amber-500' : 'bg-emerald-500'
              }`}
              style={{ width: `${Math.min((drawdownPct / maxDrawdownPct) * 100, 100)}%` }}
            />
          </div>
          <div className="flex items-center gap-3 mt-1">
            <Badge variant={risk.conservative_mode ? 'yellow' : 'green'}>
              {risk.conservative_mode ? 'Conservative Mode' : 'Normal'}
            </Badge>
            <span className="text-xs text-[#64748b]">
              High water: {fmt(risk.high_water_mark)}
            </span>
          </div>
        </div>
      </Card>

      {/* Active Positions */}
      <ActivePositions options={options} />

      {/* Agent Status */}
      {workers.length > 0 && (
        <Card title="Agent Status" subtitle="Worker performance overview">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {/* Market Regime mini-card */}
            <div className="bg-[#0a0f1e] rounded-lg p-3 border border-[#1e293b]">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium text-[#94a3b8]">Market Regime</span>
                <Badge variant={regimeColor}>{regime.regime?.replace('_', ' ').toUpperCase() || '—'}</Badge>
              </div>
              <p className="text-xs text-[#64748b]">VIX ≈ {regime.vix_level?.toFixed(1) || '—'}</p>
              <p className="text-xs text-[#64748b] mt-0.5 truncate">{regime.adjustments || ''}</p>
            </div>

            {workers.map(w => {
              const m = agentMetrics[w.name] || {}
              const color = AGENT_COLORS[w.name] || '#64748b'
              const badgeVariant = AGENT_BADGE[w.name] || 'gray'
              return (
                <div
                  key={w.name}
                  className="bg-[#0a0f1e] rounded-lg p-3 border border-[#1e293b]"
                  style={{ borderLeft: `3px solid ${color}` }}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-medium text-white truncate">{w.name}</span>
                    <Badge variant={badgeVariant}>{w.is_active ? 'Active' : 'Paused'}</Badge>
                  </div>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
                    <span className="text-[#64748b]">Trades:</span>
                    <span className="text-white">{m.total_trades || 0}</span>
                    <span className="text-[#64748b]">Win rate:</span>
                    <span className={`font-medium ${(m.win_rate || 0) >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {(m.win_rate || 0).toFixed(0)}%
                    </span>
                    <span className="text-[#64748b]">P&L:</span>
                    <span className={(m.total_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                      {fmt(m.total_pnl)}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      )}
    </div>
  )
}

// ── Helpers ────────────────────────────────────────────────────────

function buildEquityData(trades, currentEquity) {
  if (!trades.length) return []
  // Build a simplified equity curve: each trade's PnL adjusts from current equity backwards
  const sorted = [...trades].sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
  let equity = currentEquity
  const points = [{ date: 'Now', equity }]
  for (let i = sorted.length - 1; i >= 0; i--) {
    equity -= (sorted[i].pnl || 0)
    const d = new Date(sorted[i].created_at)
    points.unshift({
      date: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      equity: Math.round(equity),
    })
  }
  return points
}

function filterEquityRange(data, range) {
  if (!data.length) return data
  const now = Date.now()
  const ms = { '1W': 7, '1M': 30, '3M': 90, '6M': 180 }[range]
  if (!ms) return data
  const cutoff = now - ms * 86400000
  // Approximate: take last N points proportionally
  const keep = Math.ceil((ms / 365) * data.length)
  return data.slice(-Math.max(keep, 2))
}
