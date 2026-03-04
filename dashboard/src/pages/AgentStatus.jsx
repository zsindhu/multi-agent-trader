import { useEffect, useState } from 'react'
import { Bot, RefreshCw, Shield, Zap, Settings } from 'lucide-react'
import Card from '../components/Card'
import Badge from '../components/Badge'
import StatCard from '../components/StatCard'
import Spinner from '../components/Spinner'
import {
  fetchAgentStatus, fetchRegime, refreshRegime,
  fetchStrategies, fetchPerformance, fetchAgentPerformance,
} from '../api'

const fmt = (n) => n == null ? '—' : `$${n.toLocaleString('en-US', { minimumFractionDigits: 2 })}`

export default function AgentStatus() {
  const [status, setStatus] = useState(null)
  const [strategies, setStrategies] = useState(null)
  const [performance, setPerformance] = useState(null)
  const [agentMetrics, setAgentMetrics] = useState({})
  const [loading, setLoading] = useState(true)

  const load = async () => {
    try {
      const [s, strat, perf] = await Promise.all([
        fetchAgentStatus(),
        fetchStrategies(),
        fetchPerformance(),
      ])
      setStatus(s)
      setStrategies(strat)
      setPerformance(perf)

      // Fetch per-agent metrics
      const metrics = {}
      for (const w of (s.workers || [])) {
        try {
          metrics[w.name] = await fetchAgentPerformance(w.name, 30)
        } catch {
          metrics[w.name] = null
        }
      }
      setAgentMetrics(metrics)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleRefreshRegime = async () => {
    try {
      await refreshRegime()
      await load()
    } catch (e) {
      console.error(e)
    }
  }

  if (loading) return <Spinner />

  const regime = status?.regime || {}
  const risk = status?.risk || {}
  const workers = status?.workers || []

  const regimeColor =
    regime.regime === 'high_vol' ? 'red' :
    regime.regime === 'low_vol' ? 'green' : 'blue'

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-white flex items-center gap-2">
        <Bot size={24} /> Agent Status
      </h2>

      {/* Regime + Risk */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card
          title="Market Regime"
          action={
            <button
              onClick={handleRefreshRegime}
              className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
            >
              <RefreshCw size={12} /> Refresh
            </button>
          }
        >
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <Badge variant={regimeColor}>
                {regime.regime?.replace('_', ' ').toUpperCase() || 'UNKNOWN'}
              </Badge>
              <span className="text-sm text-[#94a3b8]">VIX ≈ {regime.vix_level?.toFixed(1) || '—'}</span>
            </div>
            <p className="text-xs text-[#64748b]">{regime.adjustments || 'No adjustments'}</p>
          </div>
        </Card>

        <Card title="Risk Status">
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <Badge variant={risk.conservative_mode ? 'yellow' : 'green'}>
                {risk.conservative_mode ? 'CONSERVATIVE' : 'NORMAL'}
              </Badge>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <span className="text-[#64748b]">Drawdown:</span>
                <span className={`ml-2 font-medium ${(risk.current_drawdown || 0) > 0.05 ? 'text-red-400' : 'text-emerald-400'}`}>
                  {((risk.current_drawdown || 0) * 100).toFixed(1)}%
                </span>
              </div>
              <div>
                <span className="text-[#64748b]">DD Limit:</span>
                <span className="ml-2 text-white">{((risk.max_drawdown_limit || 0) * 100).toFixed(0)}%</span>
              </div>
              <div>
                <span className="text-[#64748b]">High Water:</span>
                <span className="ml-2 text-white">{fmt(risk.high_water_mark)}</span>
              </div>
            </div>
          </div>
        </Card>
      </div>

      {/* Worker Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {workers.map((w) => {
          const m = agentMetrics[w.name] || {}
          const stratKey =
            w.name === 'Worker-A-CC' ? 'covered_calls' :
            w.name === 'Worker-B-CSP' ? 'cash_secured_puts' : 'wheel'
          const params = strategies?.[stratKey] || {}

          return (
            <Card key={w.name} title={w.name} subtitle={w.type}>
              <div className="space-y-4">
                {/* Performance */}
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <span className="text-[#64748b]">Trades:</span>
                    <span className="ml-1 text-white">{m.total_trades || 0}</span>
                  </div>
                  <div>
                    <span className="text-[#64748b]">Win Rate:</span>
                    <span className={`ml-1 font-medium ${(m.win_rate || 0) >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {(m.win_rate || 0).toFixed(0)}%
                    </span>
                  </div>
                  <div>
                    <span className="text-[#64748b]">P&L:</span>
                    <span className={`ml-1 font-medium ${(m.total_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {fmt(m.total_pnl)}
                    </span>
                  </div>
                  <div>
                    <span className="text-[#64748b]">Sharpe:</span>
                    <span className="ml-1 text-white">{(m.sharpe_ratio || 0).toFixed(2)}</span>
                  </div>
                </div>

                {/* Strategy params */}
                <div className="pt-3 border-t border-[#334155]">
                  <h4 className="text-xs text-[#64748b] uppercase mb-2 flex items-center gap-1">
                    <Settings size={10} /> Parameters
                  </h4>
                  <div className="grid grid-cols-2 gap-1 text-xs">
                    {Object.entries(params)
                      .filter(([k]) => !k.startsWith('_'))
                      .map(([k, v]) => (
                        <div key={k} className="flex justify-between">
                          <span className="text-[#64748b]">{k}:</span>
                          <span className="text-[#94a3b8]">{v}</span>
                        </div>
                      ))}
                  </div>
                </div>
              </div>
            </Card>
          )
        })}
      </div>

      {/* Portfolio-wide performance */}
      {performance && (
        <Card title="Portfolio Performance" subtitle="Aggregated across all agents">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <span className="text-xs text-[#64748b]">Total Trades</span>
              <p className="text-lg font-bold text-white">{performance.total_trades || 0}</p>
            </div>
            <div>
              <span className="text-xs text-[#64748b]">Total P&L</span>
              <p className={`text-lg font-bold ${(performance.total_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {fmt(performance.total_pnl)}
              </p>
            </div>
            <div>
              <span className="text-xs text-[#64748b]">Premium Collected</span>
              <p className="text-lg font-bold text-emerald-400">{fmt(performance.total_premium)}</p>
            </div>
            <div>
              <span className="text-xs text-[#64748b]">Avg Win Rate</span>
              <p className="text-lg font-bold text-white">{(performance.avg_win_rate || 0).toFixed(0)}%</p>
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}
