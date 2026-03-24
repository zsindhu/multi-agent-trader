import { useEffect, useState, lazy, Suspense } from 'react'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  BarChart, Bar, CartesianGrid, Legend,
} from 'recharts'
import { BarChart2, ScrollText, FlaskConical, Play, Filter, Lightbulb } from 'lucide-react'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Spinner from '../components/Spinner'
import StatCard from '../components/StatCard'
import SymbolScorecard from '../components/SymbolScorecard'
import {
  fetchTradeHistory, fetchJournal, fetchPerformance,
  runBacktest, getBacktestStatus, getBacktestResults,
  listBacktestResults, runCompare,
  fetchIntelligenceRecommendations, fetchIntelligenceRegimeCorrelation,
  fetchIntelligenceDeltaAnalysis, fetchIntelligenceSymbolScorecard,
} from '../api'

const RegimeCorrelationChart = lazy(() => import('../components/RegimeCorrelationChart'))
const DeltaAnalysisChart = lazy(() => import('../components/DeltaAnalysisChart'))

const fmt = (n) => n == null ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 })
const fmtShort = (n) => n == null ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 })

const TABS = ['insights', 'trades', 'journal', 'backtest']

export default function PerformancePage() {
  const [tab, setTab] = useState('insights')
  const [performance, setPerformance] = useState(null)
  const [trades, setTrades] = useState([])
  const [journal, setJournal] = useState([])
  const [agentFilter, setAgentFilter] = useState('')
  const [symbolFilter, setSymbolFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [tableLoading, setTableLoading] = useState(false)

  // Insights state
  const [recommendations, setRecommendations] = useState([])
  const [regimeCorr, setRegimeCorr] = useState(null)
  const [deltaData, setDeltaData] = useState(null)
  const [symbolData, setSymbolData] = useState(null)
  const [insightsLoading, setInsightsLoading] = useState(false)

  // Backtest state
  const [btTab, setBtTab] = useState('run')
  const [form, setForm] = useState({ agent_type: 'worker_csp', symbols: 'AAPL, MSFT, SPY', days: 180, initial_capital: 100000 })
  const [overrides, setOverrides] = useState('')
  const [running, setRunning] = useState(false)
  const [jobId, setJobId] = useState(null)
  const [result, setResult] = useState(null)
  const [compareForm, setCompareForm] = useState({ agent_type: 'worker_csp', symbols: 'AAPL, MSFT, SPY', days: 180, initial_capital: 100000, params_a: '', params_b: '' })
  const [compareJobId, setCompareJobId] = useState(null)
  const [compareResult, setCompareResult] = useState(null)
  const [comparing, setComparing] = useState(false)
  const [history, setHistory] = useState([])
  const [selectedResult, setSelectedResult] = useState(null)

  // Load summary perf + initial trades
  const loadPerf = async () => {
    try {
      const [perf, data] = await Promise.all([
        fetchPerformance(),
        fetchTradeHistory({ limit: 100 }),
      ])
      setPerformance(perf)
      setTrades(data.trades || [])
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  useEffect(() => { loadPerf() }, [])

  useEffect(() => {
    if (tab !== 'insights') return
    setInsightsLoading(true)
    Promise.all([
      fetchIntelligenceRecommendations().catch(() => []),
      fetchIntelligenceRegimeCorrelation().catch(() => null),
      fetchIntelligenceDeltaAnalysis().catch(() => null),
      fetchIntelligenceSymbolScorecard().catch(() => null),
    ]).then(([recs, regime, delta, symbols]) => {
      setRecommendations(recs || [])
      setRegimeCorr(regime)
      setDeltaData(delta)
      setSymbolData(symbols)
    }).finally(() => setInsightsLoading(false))
  }, [tab])

  // Reload table when filters or tab changes
  useEffect(() => {
    if (tab === 'backtest' || tab === 'insights') return
    setTableLoading(true)
    const params = { limit: 100 }
    if (agentFilter) params.agent = agentFilter
    if (symbolFilter) params.symbol = symbolFilter.toUpperCase()

    const load = tab === 'journal'
      ? fetchJournal(params).then(d => setJournal(d.entries || []))
      : fetchTradeHistory(params).then(d => setTrades(d.trades || []))

    load.catch(console.error).finally(() => setTableLoading(false))

    if (tab === 'backtest' && btTab === 'history') {
      listBacktestResults().then(d => setHistory(d.results || [])).catch(console.error)
    }
  }, [tab, agentFilter, symbolFilter])

  useEffect(() => {
    if (btTab === 'history') {
      listBacktestResults().then(d => setHistory(d.results || [])).catch(console.error)
    }
  }, [btTab])

  // Poll backtest job
  useEffect(() => {
    if (!jobId || result) return
    const timer = setInterval(async () => {
      try {
        const status = await getBacktestStatus(jobId)
        if (status.status === 'completed') {
          setResult(await getBacktestResults(jobId))
          setRunning(false)
          clearInterval(timer)
        } else if (status.status === 'failed') {
          setRunning(false)
          clearInterval(timer)
        }
      } catch (e) { console.error(e) }
    }, 2000)
    return () => clearInterval(timer)
  }, [jobId, result])

  // Poll compare job
  useEffect(() => {
    if (!compareJobId || compareResult) return
    const timer = setInterval(async () => {
      try {
        const status = await getBacktestStatus(compareJobId)
        if (status.status === 'completed') {
          setCompareResult(await getBacktestResults(compareJobId))
          setComparing(false)
          clearInterval(timer)
        } else if (status.status === 'failed') {
          setComparing(false)
          clearInterval(timer)
        }
      } catch (e) { console.error(e) }
    }, 2000)
    return () => clearInterval(timer)
  }, [compareJobId, compareResult])

  const handleRun = async () => {
    setRunning(true); setResult(null); setJobId(null)
    try {
      let paramOverrides = {}
      try { paramOverrides = JSON.parse(overrides || '{}') } catch { paramOverrides = {} }
      const res = await runBacktest({
        agent_type: form.agent_type,
        symbols: form.symbols.split(',').map(s => s.trim()).filter(Boolean),
        days: parseInt(form.days),
        initial_capital: parseFloat(form.initial_capital),
        param_overrides: paramOverrides,
      })
      setJobId(res.job_id)
    } catch (e) { console.error(e); setRunning(false) }
  }

  const handleCompare = async () => {
    setComparing(true); setCompareResult(null); setCompareJobId(null)
    try {
      let pa = {}, pb = {}
      try { pa = JSON.parse(compareForm.params_a || '{}') } catch { pa = {} }
      try { pb = JSON.parse(compareForm.params_b || '{}') } catch { pb = {} }
      const res = await runCompare({
        agent_type: compareForm.agent_type,
        symbols: compareForm.symbols.split(',').map(s => s.trim()).filter(Boolean),
        days: parseInt(compareForm.days),
        initial_capital: parseFloat(compareForm.initial_capital),
        params_a: pa, params_b: pb,
      })
      setCompareJobId(res.job_id)
    } catch (e) { console.error(e); setComparing(false) }
  }

  if (loading) return <div className="flex items-center justify-center h-64"><Spinner /></div>

  const totalTrades = performance?.total_trades || 0
  const hasEnoughData = totalTrades >= 5

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white flex items-center gap-2">
          <BarChart2 size={22} /> Performance
        </h2>
        <p className="text-sm text-[#64748b]">Review your trading results, journal, and run historical backtests.</p>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total Trades" value={performance?.total_trades || 0} />
        <StatCard
          label="Win Rate"
          value={performance?.avg_win_rate != null ? `${performance.avg_win_rate.toFixed(0)}%` : '—'}
          trend={performance?.avg_win_rate >= 50 ? 'up' : performance?.avg_win_rate != null ? 'down' : null}
        />
        <StatCard
          label="Total P&L"
          value={fmtShort(performance?.total_pnl)}
          trend={performance?.total_pnl > 0 ? 'up' : performance?.total_pnl < 0 ? 'down' : null}
        />
        <StatCard label="Premium Collected" value={fmtShort(performance?.total_premium)} trend="up" />
      </div>

      {/* Not enough data state */}
      {!hasEnoughData && (
        <Card>
          <div className="py-6 text-center space-y-2">
            <BarChart2 size={36} className="mx-auto text-[#334155]" />
            <p className="text-sm text-white font-medium">Not enough trading data yet</p>
            <p className="text-xs text-[#64748b]">
              Complete a few trades from the Trade Desk to unlock full analytics.
              {totalTrades > 0 && ` (${totalTrades} trades so far)`}
            </p>
          </div>
        </Card>
      )}

      {/* Tab switcher */}
      <div className="flex gap-2 border-b border-[#1e293b] pb-0">
        {TABS.map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm rounded-t-lg transition-colors capitalize border-b-2 -mb-px ${
              tab === t
                ? 'border-blue-500 text-white bg-[#111827]'
                : 'border-transparent text-[#64748b] hover:text-[#94a3b8]'
            }`}
          >
            {t === 'backtest' ? 'Backtest' : t === 'journal' ? 'Journal' : t === 'insights' ? 'Insights' : 'Trade History'}
          </button>
        ))}
      </div>

      {/* ── Insights Tab ────────────────────────────────────────── */}
      {tab === 'insights' && (
        <div className="space-y-6">
          {insightsLoading ? (
            <div className="flex justify-center py-8"><Spinner /></div>
          ) : (
            <>
              {/* What's Working */}
              <Card title="What's Working" subtitle="Rule-based insights from your closed trades">
                {recommendations.length === 0 || recommendations[0] === 'Not enough closed trade data for recommendations yet.' ? (
                  <p className="text-xs text-slate-600 italic">Not enough closed trade data for recommendations yet.</p>
                ) : (
                  <div className="space-y-1.5">
                    {recommendations.map((rec, i) => (
                      <div key={i} className="flex items-start gap-2">
                        <Lightbulb size={12} className="text-amber-400 shrink-0 mt-0.5" />
                        <p className="text-sm text-slate-300 leading-relaxed">{rec}</p>
                      </div>
                    ))}
                  </div>
                )}
              </Card>

              {/* Regime Correlation + Delta Analysis side by side */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <Card title="Win Rate by Regime" subtitle="Performance correlated with market regime at entry">
                  <Suspense fallback={<Spinner />}>
                    <RegimeCorrelationChart data={regimeCorr} />
                  </Suspense>
                </Card>
                <Card title="Win Rate by Delta" subtitle="Optimal delta range for your strategy">
                  <Suspense fallback={<Spinner />}>
                    <DeltaAnalysisChart data={deltaData} />
                  </Suspense>
                </Card>
              </div>

              {/* Symbol Scorecard */}
              <Card title="Symbol Scorecard" subtitle="Per-symbol track record — click column headers to sort">
                <SymbolScorecard data={symbolData} />
              </Card>
            </>
          )}
        </div>
      )}

      {/* Filters (trades + journal) */}
      {tab !== 'backtest' && tab !== 'insights' && (
        <div className="flex flex-wrap gap-2 items-center">
          <Filter size={14} className="text-[#64748b]" />
          <select
            value={agentFilter}
            onChange={e => setAgentFilter(e.target.value)}
            className="bg-[#1e293b] border border-[#334155] rounded-lg px-3 py-1.5 text-sm text-[#94a3b8] focus:outline-none focus:border-blue-500"
          >
            <option value="">All Agents</option>
            <option value="Covered-Calls">Covered Calls</option>
            <option value="Cash-Secured-Puts">Cash Secured Puts</option>
            <option value="Wheel">The Wheel</option>
          </select>
          <input
            type="text"
            placeholder="Symbol..."
            value={symbolFilter}
            onChange={e => setSymbolFilter(e.target.value)}
            className="bg-[#1e293b] border border-[#334155] rounded-lg px-3 py-1.5 text-sm text-white placeholder-[#64748b] w-28 focus:outline-none focus:border-blue-500"
          />
        </div>
      )}

      {/* ── Trades Tab ── */}
      {tab === 'trades' && (
        <Card>
          {tableLoading ? <Spinner /> : trades.length === 0 ? (
            <p className="text-sm text-[#64748b] text-center py-8">No trades found. Head to the Trade Desk to place your first trade.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[#64748b] text-xs uppercase border-b border-[#334155]">
                    <th className="text-left py-2.5 px-2">Date</th>
                    <th className="text-left py-2.5 px-2">Agent</th>
                    <th className="text-left py-2.5 px-2">Symbol</th>
                    <th className="text-left py-2.5 px-2">Type</th>
                    <th className="text-right py-2.5 px-2">Qty</th>
                    <th className="text-right py-2.5 px-2">Price</th>
                    <th className="text-right py-2.5 px-2">Premium</th>
                    <th className="text-right py-2.5 px-2">P&L</th>
                    <th className="text-left py-2.5 px-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map(t => (
                    <tr key={t.id} className="border-b border-[#334155]/40 hover:bg-[#334155]/20 transition-colors">
                      <td className="py-2.5 px-2 text-[#94a3b8] text-xs">{t.created_at ? new Date(t.created_at).toLocaleDateString() : '—'}</td>
                      <td className="py-2.5 px-2"><Badge variant="blue">{t.agent_name}</Badge></td>
                      <td className="py-2.5 px-2 font-medium text-white font-mono">{t.symbol}</td>
                      <td className="py-2.5 px-2 text-[#94a3b8]">{t.trade_type}</td>
                      <td className="py-2.5 px-2 text-right text-white">{t.quantity}</td>
                      <td className="py-2.5 px-2 text-right text-white">{fmt(t.price)}</td>
                      <td className="py-2.5 px-2 text-right text-emerald-400">{fmt(t.premium)}</td>
                      <td className={`py-2.5 px-2 text-right font-medium ${t.pnl != null ? (t.pnl >= 0 ? 'text-emerald-400' : 'text-red-400') : 'text-[#64748b]'}`}>
                        {fmt(t.pnl)}
                      </td>
                      <td className="py-2.5 px-2">
                        <Badge variant={t.status === 'filled' ? 'green' : 'gray'}>{t.status}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {/* ── Journal Tab ── */}
      {tab === 'journal' && (
        <Card>
          {tableLoading ? <Spinner /> : journal.length === 0 ? (
            <p className="text-sm text-[#64748b] text-center py-8">No journal entries yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[#64748b] text-xs uppercase border-b border-[#334155]">
                    <th className="text-left py-2.5 px-2">Entry</th>
                    <th className="text-left py-2.5 px-2">Agent</th>
                    <th className="text-left py-2.5 px-2">Symbol</th>
                    <th className="text-left py-2.5 px-2">Contract</th>
                    <th className="text-right py-2.5 px-2">Strike</th>
                    <th className="text-right py-2.5 px-2">Delta</th>
                    <th className="text-right py-2.5 px-2">DTE</th>
                    <th className="text-right py-2.5 px-2">IV Rank</th>
                    <th className="text-right py-2.5 px-2">P&L</th>
                    <th className="text-left py-2.5 px-2">Exit</th>
                    <th className="text-right py-2.5 px-2">Days</th>
                  </tr>
                </thead>
                <tbody>
                  {journal.map(e => (
                    <tr key={e.id} className="border-b border-[#334155]/40 hover:bg-[#334155]/20 transition-colors">
                      <td className="py-2.5 px-2 text-[#94a3b8] text-xs">{e.entry_at ? new Date(e.entry_at).toLocaleDateString() : '—'}</td>
                      <td className="py-2.5 px-2"><Badge variant="blue">{e.agent_name}</Badge></td>
                      <td className="py-2.5 px-2 font-medium text-white font-mono">{e.symbol}</td>
                      <td className="py-2.5 px-2">
                        <Badge variant={e.contract_type === 'put' ? 'red' : 'green'}>{e.side} {e.contract_type}</Badge>
                      </td>
                      <td className="py-2.5 px-2 text-right text-white">{fmt(e.strike)}</td>
                      <td className="py-2.5 px-2 text-right text-[#94a3b8]">{e.delta_at_entry?.toFixed(2) ?? '—'}</td>
                      <td className="py-2.5 px-2 text-right text-[#94a3b8]">{e.dte_at_entry ?? '—'}</td>
                      <td className="py-2.5 px-2 text-right text-[#94a3b8]">{e.entry_iv_rank?.toFixed(0) ?? '—'}</td>
                      <td className={`py-2.5 px-2 text-right font-medium ${e.realized_pnl != null ? (e.realized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400') : 'text-[#64748b]'}`}>
                        {fmt(e.realized_pnl)}
                      </td>
                      <td className="py-2.5 px-2">
                        {e.exit_reason ? <Badge variant="gray">{e.exit_reason}</Badge> : <span className="text-[#64748b] text-xs">Open</span>}
                      </td>
                      <td className="py-2.5 px-2 text-right text-[#94a3b8]">{e.days_held ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {/* ── Backtest Tab ── */}
      {tab === 'backtest' && (
        <div className="space-y-4">
          {/* Sub-tabs */}
          <div className="flex gap-2">
            {['run', 'compare', 'history'].map(t => (
              <button
                key={t}
                onClick={() => setBtTab(t)}
                className={`px-4 py-2 text-sm rounded-lg transition-colors capitalize ${
                  btTab === t ? 'bg-blue-600 text-white' : 'bg-[#1e293b] text-[#94a3b8] hover:text-white border border-[#334155]'
                }`}
              >
                {t}
              </button>
            ))}
          </div>

          {/* Run */}
          {btTab === 'run' && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <Card title="Configuration" className="lg:col-span-1">
                <div className="space-y-3">
                  <label className="block">
                    <span className="text-xs text-[#94a3b8]">Agent Type</span>
                    <select value={form.agent_type} onChange={e => setForm({ ...form, agent_type: e.target.value })}
                      className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500">
                      <option value="worker_csp">Cash Secured Puts</option>
                      <option value="worker_cc">Covered Calls</option>
                      <option value="worker_wheel">The Wheel</option>
                    </select>
                  </label>
                  <label className="block">
                    <span className="text-xs text-[#94a3b8]">Symbols (comma-separated)</span>
                    <input type="text" value={form.symbols} onChange={e => setForm({ ...form, symbols: e.target.value })}
                      className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500" />
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    <label className="block">
                      <span className="text-xs text-[#94a3b8]">Days</span>
                      <input type="number" value={form.days} onChange={e => setForm({ ...form, days: e.target.value })}
                        className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500" />
                    </label>
                    <label className="block">
                      <span className="text-xs text-[#94a3b8]">Capital</span>
                      <input type="number" value={form.initial_capital} onChange={e => setForm({ ...form, initial_capital: e.target.value })}
                        className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500" />
                    </label>
                  </div>
                  <label className="block">
                    <span className="text-xs text-[#94a3b8]">Param Overrides (JSON)</span>
                    <textarea value={overrides} onChange={e => setOverrides(e.target.value)} placeholder='{"delta_target": -0.20}' rows={3}
                      className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-blue-500" />
                  </label>
                  <button onClick={handleRun} disabled={running}
                    className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg disabled:opacity-50">
                    <Play size={14} className={running ? 'animate-pulse' : ''} />
                    {running ? 'Running...' : 'Run Backtest'}
                  </button>
                </div>
              </Card>
              <div className="lg:col-span-2 space-y-4">
                {running && !result && (
                  <Card>
                    <div className="flex items-center gap-3 py-8 justify-center">
                      <div className="w-5 h-5 border-2 border-[#334155] border-t-blue-500 rounded-full animate-spin" />
                      <span className="text-[#94a3b8]">Running backtest…</span>
                    </div>
                  </Card>
                )}
                {result && <BacktestResultView data={result} />}
              </div>
            </div>
          )}

          {/* Compare */}
          {btTab === 'compare' && (
            <div className="space-y-4">
              <Card title="Compare Parameters">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {['a', 'b'].map(side => (
                    <div key={side} className="space-y-2">
                      <h4 className="text-xs font-semibold text-[#94a3b8] uppercase">Config {side.toUpperCase()}</h4>
                      <label className="block">
                        <span className="text-xs text-[#64748b]">Param Overrides (JSON)</span>
                        <textarea
                          value={compareForm[`params_${side}`]}
                          onChange={e => setCompareForm({ ...compareForm, [`params_${side}`]: e.target.value })}
                          placeholder={`{"delta_target": ${side === 'a' ? '-0.25' : '-0.20'}}`} rows={3}
                          className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-blue-500"
                        />
                      </label>
                    </div>
                  ))}
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2 mt-3">
                  <label className="block">
                    <span className="text-xs text-[#64748b]">Agent</span>
                    <select value={compareForm.agent_type} onChange={e => setCompareForm({ ...compareForm, agent_type: e.target.value })}
                      className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500">
                      <option value="worker_csp">Cash Secured Puts</option>
                      <option value="worker_cc">Covered Calls</option>
                      <option value="worker_wheel">The Wheel</option>
                    </select>
                  </label>
                  <label className="block">
                    <span className="text-xs text-[#64748b]">Symbols</span>
                    <input type="text" value={compareForm.symbols} onChange={e => setCompareForm({ ...compareForm, symbols: e.target.value })}
                      className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500" />
                  </label>
                  <label className="block">
                    <span className="text-xs text-[#64748b]">Days</span>
                    <input type="number" value={compareForm.days} onChange={e => setCompareForm({ ...compareForm, days: e.target.value })}
                      className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500" />
                  </label>
                </div>
                <button onClick={handleCompare} disabled={comparing}
                  className="mt-3 flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg disabled:opacity-50">
                  <Play size={14} /> {comparing ? 'Comparing...' : 'Run Comparison'}
                </button>
              </Card>
              {comparing && !compareResult && (
                <Card><div className="flex items-center gap-3 py-8 justify-center">
                  <div className="w-5 h-5 border-2 border-[#334155] border-t-blue-500 rounded-full animate-spin" />
                  <span className="text-[#94a3b8]">Running comparison…</span>
                </div></Card>
              )}
              {compareResult && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <BacktestResultView data={compareResult.result_a} title="Config A" />
                  <BacktestResultView data={compareResult.result_b} title="Config B" />
                </div>
              )}
            </div>
          )}

          {/* History */}
          {btTab === 'history' && (
            <Card title="Backtest History">
              {history.length === 0 ? (
                <p className="text-sm text-[#64748b] text-center py-8">No saved backtests yet.</p>
              ) : (
                <div className="space-y-2">
                  {history.map(h => (
                    <div key={h.job_id} className="flex items-center justify-between px-3 py-2.5 bg-[#0a0f1e] rounded-lg border border-[#1e293b]">
                      <div>
                        <span className="text-sm font-medium text-white">{h.agent_type}</span>
                        <span className="text-xs text-[#64748b] ml-3">{h.symbols?.join(', ')} · {h.days}d</span>
                      </div>
                      <button
                        onClick={() => getBacktestResults(h.job_id).then(d => setSelectedResult(d)).catch(console.error)}
                        className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
                      >
                        View Results
                      </button>
                    </div>
                  ))}
                  {selectedResult && (
                    <div className="mt-4">
                      <BacktestResultView data={selectedResult} />
                    </div>
                  )}
                </div>
              )}
            </Card>
          )}
        </div>
      )}
    </div>
  )
}

// ── BacktestResultView ───────────────────────────────────────────────
function BacktestResultView({ data, title }) {
  if (!data) return null
  const s = data.summary || {}
  const equityData = data.equity_curve || []
  const monthlyData = data.monthly_returns || []
  const symbolData = data.per_symbol || []

  return (
    <div className="space-y-4">
      {title && <h4 className="text-sm font-semibold text-[#94a3b8] uppercase">{title}</h4>}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: 'Total Return', value: s.total_return != null ? `${s.total_return.toFixed(1)}%` : '—', good: s.total_return > 0 },
          { label: 'Sharpe', value: s.sharpe_ratio?.toFixed(2) ?? '—', good: s.sharpe_ratio > 1 },
          { label: 'Win Rate', value: s.win_rate != null ? `${s.win_rate.toFixed(0)}%` : '—', good: s.win_rate >= 50 },
          { label: 'Max DD', value: s.max_drawdown != null ? `${(s.max_drawdown * 100).toFixed(1)}%` : '—', good: (s.max_drawdown || 0) < 0.10 },
        ].map(m => (
          <div key={m.label} className="bg-[#0a0f1e] rounded-lg p-3 border border-[#1e293b]">
            <span className="text-xs text-[#64748b]">{m.label}</span>
            <p className={`text-lg font-bold mt-0.5 ${m.good ? 'text-emerald-400' : 'text-red-400'}`}>{m.value}</p>
          </div>
        ))}
      </div>

      {equityData.length > 1 && (
        <Card title="Equity Curve">
          <ResponsiveContainer width="100%" height={150}>
            <LineChart data={equityData}>
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#64748b' }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 10, fill: '#64748b' }} tickLine={false} axisLine={false} width={45} tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
              <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }} labelStyle={{ color: '#94a3b8', fontSize: 11 }} formatter={v => [`$${v.toLocaleString()}`, 'Equity']} />
              <Line type="monotone" dataKey="equity" stroke="#3b82f6" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      )}

      {symbolData.length > 0 && (
        <Card title="Per-Symbol">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[#64748b] text-xs uppercase border-b border-[#334155]">
                  <th className="text-left py-2 px-2">Symbol</th>
                  <th className="text-right py-2 px-2">Trades</th>
                  <th className="text-right py-2 px-2">Win Rate</th>
                  <th className="text-right py-2 px-2">P&L</th>
                </tr>
              </thead>
              <tbody>
                {symbolData.map(r => (
                  <tr key={r.symbol} className="border-b border-[#334155]/40">
                    <td className="py-2 px-2 font-medium text-white">{r.symbol}</td>
                    <td className="py-2 px-2 text-right text-[#94a3b8]">{r.trades}</td>
                    <td className={`py-2 px-2 text-right ${r.win_rate >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>{r.win_rate?.toFixed(0)}%</td>
                    <td className={`py-2 px-2 text-right font-medium ${r.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>${r.pnl?.toFixed(0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
