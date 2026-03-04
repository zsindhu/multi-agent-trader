import { useEffect, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend,
  BarChart, Bar, CartesianGrid,
} from 'recharts'
import { FlaskConical, Play, ListChecks } from 'lucide-react'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Spinner from '../components/Spinner'
import StatCard from '../components/StatCard'
import {
  runBacktest, getBacktestStatus, getBacktestResults,
  listBacktestResults, runCompare, listJobs,
} from '../api'

const fmt = (n) => n == null ? '—' : `$${n.toLocaleString('en-US', { minimumFractionDigits: 2 })}`

export default function Backtest() {
  const [tab, setTab] = useState('run')

  // Form state
  const [form, setForm] = useState({
    agent_type: 'worker_csp',
    symbols: 'AAPL, MSFT, SPY',
    days: 180,
    initial_capital: 100000,
  })
  const [overrides, setOverrides] = useState('')
  const [running, setRunning] = useState(false)
  const [jobId, setJobId] = useState(null)
  const [result, setResult] = useState(null)
  const [pollTimer, setPollTimer] = useState(null)

  // Compare state
  const [compareForm, setCompareForm] = useState({
    agent_type: 'worker_csp',
    symbols: 'AAPL, MSFT, SPY',
    days: 180,
    initial_capital: 100000,
    params_a: '',
    params_b: '',
  })
  const [compareJobId, setCompareJobId] = useState(null)
  const [compareResult, setCompareResult] = useState(null)
  const [comparing, setComparing] = useState(false)

  // History
  const [history, setHistory] = useState([])
  const [selectedResult, setSelectedResult] = useState(null)

  useEffect(() => {
    if (tab === 'history') {
      listBacktestResults().then((d) => setHistory(d.results || [])).catch(console.error)
    }
  }, [tab])

  // Poll for results
  useEffect(() => {
    if (!jobId || result) return
    const timer = setInterval(async () => {
      try {
        const status = await getBacktestStatus(jobId)
        if (status.status === 'completed') {
          const res = await getBacktestResults(jobId)
          setResult(res)
          setRunning(false)
          clearInterval(timer)
        } else if (status.status === 'failed') {
          console.error('Backtest failed:', status.error)
          setRunning(false)
          clearInterval(timer)
        }
      } catch (e) {
        console.error(e)
      }
    }, 2000)
    return () => clearInterval(timer)
  }, [jobId, result])

  // Compare poll
  useEffect(() => {
    if (!compareJobId || compareResult) return
    const timer = setInterval(async () => {
      try {
        const status = await getBacktestStatus(compareJobId)
        if (status.status === 'completed') {
          const res = await getBacktestResults(compareJobId)
          setCompareResult(res)
          setComparing(false)
          clearInterval(timer)
        } else if (status.status === 'failed') {
          setComparing(false)
          clearInterval(timer)
        }
      } catch (e) {
        console.error(e)
      }
    }, 2000)
    return () => clearInterval(timer)
  }, [compareJobId, compareResult])

  const handleRun = async () => {
    setRunning(true)
    setResult(null)
    setJobId(null)
    try {
      let paramOverrides = {}
      if (overrides.trim()) {
        try { paramOverrides = JSON.parse(overrides) } catch { paramOverrides = {} }
      }
      const res = await runBacktest({
        agent_type: form.agent_type,
        symbols: form.symbols.split(',').map((s) => s.trim()).filter(Boolean),
        days: parseInt(form.days),
        initial_capital: parseFloat(form.initial_capital),
        param_overrides: paramOverrides,
      })
      setJobId(res.job_id)
    } catch (e) {
      console.error(e)
      setRunning(false)
    }
  }

  const handleCompare = async () => {
    setComparing(true)
    setCompareResult(null)
    setCompareJobId(null)
    try {
      let pa = {}, pb = {}
      try { pa = JSON.parse(compareForm.params_a || '{}') } catch { pa = {} }
      try { pb = JSON.parse(compareForm.params_b || '{}') } catch { pb = {} }
      const res = await runCompare({
        agent_type: compareForm.agent_type,
        symbols: compareForm.symbols.split(',').map((s) => s.trim()).filter(Boolean),
        days: parseInt(compareForm.days),
        initial_capital: parseFloat(compareForm.initial_capital),
        params_a: pa,
        params_b: pb,
      })
      setCompareJobId(res.job_id)
    } catch (e) {
      console.error(e)
      setComparing(false)
    }
  }

  const viewHistorical = async (jid) => {
    try {
      const data = await getBacktestResults(jid)
      setSelectedResult(data)
    } catch (e) {
      console.error(e)
    }
  }

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-white flex items-center gap-2">
        <FlaskConical size={24} /> Backtest Dashboard
      </h2>

      {/* Tabs */}
      <div className="flex gap-2">
        {['run', 'compare', 'history'].map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm rounded-lg transition-colors capitalize ${
              tab === t
                ? 'bg-blue-600 text-white'
                : 'bg-[#1e293b] text-[#94a3b8] hover:text-white border border-[#334155]'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* ── RUN TAB ── */}
      {tab === 'run' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Card title="Configuration" className="lg:col-span-1">
            <div className="space-y-3">
              <label className="block">
                <span className="text-xs text-[#94a3b8]">Agent Type</span>
                <select
                  value={form.agent_type}
                  onChange={(e) => setForm({ ...form, agent_type: e.target.value })}
                  className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="worker_csp">Cash Secured Puts</option>
                  <option value="worker_cc">Covered Calls</option>
                  <option value="worker_wheel">The Wheel</option>
                </select>
              </label>
              <label className="block">
                <span className="text-xs text-[#94a3b8]">Symbols (comma-separated)</span>
                <input
                  type="text"
                  value={form.symbols}
                  onChange={(e) => setForm({ ...form, symbols: e.target.value })}
                  className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                />
              </label>
              <div className="grid grid-cols-2 gap-2">
                <label className="block">
                  <span className="text-xs text-[#94a3b8]">Days</span>
                  <input
                    type="number"
                    value={form.days}
                    onChange={(e) => setForm({ ...form, days: e.target.value })}
                    className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                  />
                </label>
                <label className="block">
                  <span className="text-xs text-[#94a3b8]">Capital</span>
                  <input
                    type="number"
                    value={form.initial_capital}
                    onChange={(e) => setForm({ ...form, initial_capital: e.target.value })}
                    className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                  />
                </label>
              </div>
              <label className="block">
                <span className="text-xs text-[#94a3b8]">Param Overrides (JSON)</span>
                <textarea
                  value={overrides}
                  onChange={(e) => setOverrides(e.target.value)}
                  placeholder='{"delta_target": -0.20}'
                  rows={3}
                  className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-blue-500"
                />
              </label>
              <button
                onClick={handleRun}
                disabled={running}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
              >
                <Play size={14} className={running ? 'animate-pulse' : ''} />
                {running ? 'Running...' : 'Run Backtest'}
              </button>
            </div>
          </Card>

          {/* Results */}
          <div className="lg:col-span-2 space-y-4">
            {running && !result && (
              <Card>
                <div className="flex items-center gap-3 py-8 justify-center">
                  <div className="w-5 h-5 border-2 border-[#334155] border-t-blue-500 rounded-full animate-spin" />
                  <span className="text-[#94a3b8]">Running backtest... this may take a minute.</span>
                </div>
              </Card>
            )}

            {result && <BacktestResultView data={result} />}
          </div>
        </div>
      )}

      {/* ── COMPARE TAB ── */}
      {tab === 'compare' && (
        <div className="space-y-6">
          <Card title="Compare Parameters">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-3">
                <label className="block">
                  <span className="text-xs text-[#94a3b8]">Agent Type</span>
                  <select
                    value={compareForm.agent_type}
                    onChange={(e) => setCompareForm({ ...compareForm, agent_type: e.target.value })}
                    className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                  >
                    <option value="worker_csp">Cash Secured Puts</option>
                    <option value="worker_cc">Covered Calls</option>
                    <option value="worker_wheel">The Wheel</option>
                  </select>
                </label>
                <label className="block">
                  <span className="text-xs text-[#94a3b8]">Symbols</span>
                  <input
                    type="text"
                    value={compareForm.symbols}
                    onChange={(e) => setCompareForm({ ...compareForm, symbols: e.target.value })}
                    className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                  />
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <label className="block">
                    <span className="text-xs text-[#94a3b8]">Days</span>
                    <input
                      type="number"
                      value={compareForm.days}
                      onChange={(e) => setCompareForm({ ...compareForm, days: e.target.value })}
                      className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                    />
                  </label>
                  <label className="block">
                    <span className="text-xs text-[#94a3b8]">Capital</span>
                    <input
                      type="number"
                      value={compareForm.initial_capital}
                      onChange={(e) => setCompareForm({ ...compareForm, initial_capital: e.target.value })}
                      className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                    />
                  </label>
                </div>
              </div>
              <div className="space-y-3">
                <label className="block">
                  <span className="text-xs text-[#94a3b8]">Params A (JSON)</span>
                  <textarea
                    value={compareForm.params_a}
                    onChange={(e) => setCompareForm({ ...compareForm, params_a: e.target.value })}
                    placeholder='{"delta_target": -0.20}'
                    rows={3}
                    className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-blue-500"
                  />
                </label>
                <label className="block">
                  <span className="text-xs text-[#94a3b8]">Params B (JSON)</span>
                  <textarea
                    value={compareForm.params_b}
                    onChange={(e) => setCompareForm({ ...compareForm, params_b: e.target.value })}
                    placeholder='{"delta_target": -0.30}'
                    rows={3}
                    className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-blue-500"
                  />
                </label>
              </div>
            </div>
            <button
              onClick={handleCompare}
              disabled={comparing}
              className="mt-4 w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
            >
              <Play size={14} className={comparing ? 'animate-pulse' : ''} />
              {comparing ? 'Running...' : 'Run Comparison'}
            </button>
          </Card>

          {comparing && !compareResult && (
            <Card>
              <div className="flex items-center gap-3 py-8 justify-center">
                <div className="w-5 h-5 border-2 border-[#334155] border-t-blue-500 rounded-full animate-spin" />
                <span className="text-[#94a3b8]">Running comparison backtests...</span>
              </div>
            </Card>
          )}

          {compareResult && (
            <div className="space-y-4">
              {/* Side-by-side stats */}
              <Card title="Comparison Results">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-[#64748b] text-xs uppercase border-b border-[#334155]">
                        <th className="text-left py-3 px-2">Metric</th>
                        <th className="text-right py-3 px-2">Params A</th>
                        <th className="text-right py-3 px-2">Params B</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[
                        ['Total Return', `${(compareResult.params_a?.total_return || 0).toFixed(2)}%`, `${(compareResult.params_b?.total_return || 0).toFixed(2)}%`],
                        ['Sharpe', (compareResult.params_a?.sharpe_ratio || 0).toFixed(2), (compareResult.params_b?.sharpe_ratio || 0).toFixed(2)],
                        ['Max Drawdown', `${(compareResult.params_a?.max_drawdown || 0).toFixed(2)}%`, `${(compareResult.params_b?.max_drawdown || 0).toFixed(2)}%`],
                        ['Win Rate', `${(compareResult.params_a?.win_rate || 0).toFixed(1)}%`, `${(compareResult.params_b?.win_rate || 0).toFixed(1)}%`],
                        ['Trade Count', compareResult.params_a?.trade_count || 0, compareResult.params_b?.trade_count || 0],
                        ['Profit Factor', (compareResult.params_a?.profit_factor || 0).toFixed(2), (compareResult.params_b?.profit_factor || 0).toFixed(2)],
                        ['Final Value', fmt(compareResult.params_a?.final_value), fmt(compareResult.params_b?.final_value)],
                      ].map(([label, a, b]) => (
                        <tr key={label} className="border-b border-[#334155]/50">
                          <td className="py-2 px-2 text-[#94a3b8]">{label}</td>
                          <td className="py-2 px-2 text-right text-white">{a}</td>
                          <td className="py-2 px-2 text-right text-white">{b}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>

              {/* Equity curves overlay */}
              {(compareResult.params_a?.equity_curve || compareResult.params_b?.equity_curve) && (
                <Card title="Equity Curves">
                  <EquityCurveCompare
                    curveA={compareResult.params_a?.equity_curve || []}
                    curveB={compareResult.params_b?.equity_curve || []}
                  />
                </Card>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── HISTORY TAB ── */}
      {tab === 'history' && (
        <div className="space-y-4">
          <Card title="Saved Results" subtitle={`${history.length} backtests`}>
            {history.length === 0 ? (
              <p className="text-sm text-[#64748b] text-center py-8">No saved backtest results</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-[#64748b] text-xs uppercase border-b border-[#334155]">
                      <th className="text-left py-3 px-2">ID</th>
                      <th className="text-left py-3 px-2">Agent</th>
                      <th className="text-left py-3 px-2">Symbols</th>
                      <th className="text-left py-3 px-2">Period</th>
                      <th className="text-right py-3 px-2">Return</th>
                      <th className="text-right py-3 px-2">Sharpe</th>
                      <th className="text-right py-3 px-2">Trades</th>
                      <th className="text-left py-3 px-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((h) => (
                      <tr key={h.job_id} className="border-b border-[#334155]/50 hover:bg-[#334155]/30">
                        <td className="py-3 px-2 font-mono text-xs text-[#94a3b8]">{h.job_id}</td>
                        <td className="py-3 px-2"><Badge variant="blue">{h.agent_type}</Badge></td>
                        <td className="py-3 px-2 text-xs">{(h.symbols || []).slice(0, 3).join(', ')}</td>
                        <td className="py-3 px-2 text-xs">{h.start_date} → {h.end_date}</td>
                        <td className={`py-3 px-2 text-right font-medium ${(h.total_return || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {(h.total_return || 0).toFixed(2)}%
                        </td>
                        <td className="py-3 px-2 text-right">{(h.sharpe_ratio || 0).toFixed(2)}</td>
                        <td className="py-3 px-2 text-right">{h.trade_count || 0}</td>
                        <td className="py-3 px-2">
                          <button
                            onClick={() => viewHistorical(h.job_id)}
                            className="text-blue-400 hover:text-blue-300 text-xs"
                          >
                            View
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {selectedResult && <BacktestResultView data={selectedResult} />}
        </div>
      )}
    </div>
  )
}


/* ── Subcomponents ────────────────────────────────────────────── */

function BacktestResultView({ data }) {
  const equityData = (data.equity_curve || []).map(([date, value]) => ({
    date: date?.slice(5) || '',
    value,
  }))

  const monthlyData = Object.entries(data.monthly_returns || {}).map(([month, ret]) => ({
    month: month?.slice(5) || month,
    return: ret,
  }))

  return (
    <div className="space-y-4">
      {/* Summary Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard label="Total Return" value={`${(data.total_return || 0).toFixed(2)}%`} trend={(data.total_return || 0) >= 0 ? 'up' : 'down'} />
        <StatCard label="Sharpe Ratio" value={(data.sharpe_ratio || 0).toFixed(2)} />
        <StatCard label="Max Drawdown" value={`${(data.max_drawdown || 0).toFixed(2)}%`} trend="down" />
        <StatCard label="Win Rate" value={`${(data.win_rate || 0).toFixed(1)}%`} />
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard label="Trade Count" value={data.trade_count || 0} />
        <StatCard label="Profit Factor" value={(data.profit_factor || 0).toFixed(2)} />
        <StatCard label="Premium Collected" value={fmt(data.total_premium_collected)} trend="up" />
        <StatCard label="Final Value" value={fmt(data.final_value)} />
      </div>

      {/* Equity Curve */}
      {equityData.length > 0 && (
        <Card title="Equity Curve">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={equityData}>
                <defs>
                  <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="date" stroke="#64748b" fontSize={10} tickLine={false} />
                <YAxis stroke="#64748b" fontSize={10} tickLine={false} tickFormatter={(v) => `$${(v/1000).toFixed(0)}k`} />
                <Tooltip
                  contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', fontSize: '12px' }}
                  labelStyle={{ color: '#94a3b8' }}
                  formatter={(v) => [`$${v.toLocaleString()}`, 'Value']}
                />
                <Area type="monotone" dataKey="value" stroke="#3b82f6" fill="url(#colorValue)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {/* Monthly Returns */}
      {monthlyData.length > 0 && (
        <Card title="Monthly Returns">
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={monthlyData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="month" stroke="#64748b" fontSize={10} />
                <YAxis stroke="#64748b" fontSize={10} tickFormatter={(v) => `${v}%`} />
                <Tooltip
                  contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', fontSize: '12px' }}
                  formatter={(v) => [`${v.toFixed(2)}%`, 'Return']}
                />
                <Bar
                  dataKey="return"
                  fill="#3b82f6"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {/* Per-Symbol Breakdown */}
      {data.per_symbol && Object.keys(data.per_symbol).length > 0 && (
        <Card title="Per-Symbol Breakdown">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[#64748b] text-xs uppercase border-b border-[#334155]">
                  <th className="text-left py-2 px-2">Symbol</th>
                  <th className="text-right py-2 px-2">Trades</th>
                  <th className="text-right py-2 px-2">Win Rate</th>
                  <th className="text-right py-2 px-2">Total P&L</th>
                  <th className="text-right py-2 px-2">Avg P&L</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.per_symbol)
                  .sort(([, a], [, b]) => (b.total_pnl || 0) - (a.total_pnl || 0))
                  .map(([sym, s]) => (
                    <tr key={sym} className="border-b border-[#334155]/50">
                      <td className="py-2 px-2 font-medium text-white">{sym}</td>
                      <td className="py-2 px-2 text-right">{s.trades}</td>
                      <td className="py-2 px-2 text-right">{s.win_rate}%</td>
                      <td className={`py-2 px-2 text-right font-medium ${s.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {fmt(s.total_pnl)}
                      </td>
                      <td className="py-2 px-2 text-right">{fmt(s.avg_pnl)}</td>
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


function EquityCurveCompare({ curveA, curveB }) {
  // Merge both curves by date
  const dateMap = {}
  for (const [date, val] of curveA) {
    dateMap[date] = { date: date?.slice(5) || '', a: val }
  }
  for (const [date, val] of curveB) {
    if (!dateMap[date]) dateMap[date] = { date: date?.slice(5) || '' }
    dateMap[date].b = val
  }
  const merged = Object.values(dateMap).sort((x, y) => (x.date > y.date ? 1 : -1))

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={merged}>
          <XAxis dataKey="date" stroke="#64748b" fontSize={10} tickLine={false} />
          <YAxis stroke="#64748b" fontSize={10} tickLine={false} tickFormatter={(v) => `$${(v/1000).toFixed(0)}k`} />
          <Tooltip
            contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', fontSize: '12px' }}
          />
          <Legend />
          <Line type="monotone" dataKey="a" name="Params A" stroke="#3b82f6" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="b" name="Params B" stroke="#f59e0b" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
