import { useEffect, useState } from 'react'
import { Activity, Database, Cpu, Download, RefreshCw } from 'lucide-react'
import Card from '../components/Card'
import Spinner from '../components/Spinner'
import { fetchDiagnosticsHealth, fetchDiagnosticsDbCounts, fetchLlmUsage } from '../api'

function StatusPill({ label, status }) {
  const ok = status === 'ok'
  const notConfigured = status === 'not_configured'
  const color = ok
    ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
    : notConfigured
    ? 'bg-slate-500/10 border-slate-500/30 text-slate-400'
    : 'bg-red-500/10 border-red-500/30 text-red-400'
  const dot = ok ? 'bg-emerald-400' : notConfigured ? 'bg-slate-500' : 'bg-red-400'
  const text = ok ? 'OK' : notConfigured ? 'Not configured' : (status || 'Error')
  return (
    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs ${color}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />
      <span className="font-medium text-slate-300">{label}</span>
      <span className="ml-auto">{text}</span>
    </div>
  )
}

function CostBar({ cost, limit }) {
  const pct = Math.min(100, (cost / limit) * 100)
  const color = pct >= 90 ? 'bg-red-500' : pct >= 60 ? 'bg-amber-500' : 'bg-emerald-500'
  return (
    <div className="mt-2">
      <div className="flex justify-between text-xs text-slate-400 mb-1">
        <span>${cost?.toFixed(4) ?? '0.0000'} spent</span>
        <span>${limit?.toFixed(2) ?? '1.00'} limit</span>
      </div>
      <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function ExportButton({ href, filename, children }) {
  return (
    <a
      href={href}
      download={filename}
      className="flex items-center gap-2 px-4 py-2 bg-[#334155] hover:bg-[#475569] text-white text-sm rounded-lg transition-colors"
    >
      <Download size={14} />
      {children}
    </a>
  )
}

export default function DiagnosticsPage() {
  const [health, setHealth] = useState(null)
  const [llmUsage, setLlmUsage] = useState(null)
  const [dbCounts, setDbCounts] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const load = async (showRefresh = false) => {
    if (showRefresh) setRefreshing(true)
    try {
      const [h, u, db] = await Promise.allSettled([
        fetchDiagnosticsHealth(),
        fetchLlmUsage(),
        fetchDiagnosticsDbCounts(),
      ])
      if (h.status === 'fulfilled') setHealth(h.value)
      if (u.status === 'fulfilled') setLlmUsage(u.value)
      if (db.status === 'fulfilled') setDbCounts(db.value)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    load()
    const t = setInterval(() => load(), 30_000)
    return () => clearInterval(t)
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <Spinner />
      </div>
    )
  }

  const checks = health?.checks || {}

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white">System Diagnostics</h2>
          <p className="text-xs text-slate-500 mt-0.5">Health checks, LLM usage, and data exports</p>
        </div>
        <button
          onClick={() => load(true)}
          disabled={refreshing}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-[#1e293b] border border-[#334155] text-slate-400 hover:text-white text-xs rounded-lg transition-colors"
        >
          <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* System Health */}
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <Activity size={16} className="text-slate-400" />
          <h3 className="text-sm font-semibold text-white">System Health</h3>
          {health && (
            <span className={`ml-auto text-xs px-2 py-0.5 rounded-full ${
              health.status === 'ok'
                ? 'bg-emerald-500/10 text-emerald-400'
                : 'bg-amber-500/10 text-amber-400'
            }`}>
              {health.status === 'ok' ? 'All systems OK' : 'Degraded'}
            </span>
          )}
        </div>
        <div className="space-y-2">
          <StatusPill label="Alpaca Broker" status={checks.alpaca} />
          <StatusPill label="Database" status={checks.database} />
          <StatusPill label="LLM Service" status={checks.llm} />
        </div>
      </Card>

      {/* LLM Usage */}
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <Cpu size={16} className="text-purple-400" />
          <h3 className="text-sm font-semibold text-white">LLM Usage</h3>
          {llmUsage?.reset_date && (
            <span className="ml-auto text-xs text-slate-500">resets at UTC midnight</span>
          )}
        </div>
        {!llmUsage?.enabled ? (
          <p className="text-sm text-slate-500 italic">LLM not configured (no ANTHROPIC_API_KEY)</p>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-slate-900/40 rounded-lg p-3">
                <p className="text-xs text-slate-500 mb-1">Input tokens today</p>
                <p className="text-lg font-semibold text-white">
                  {llmUsage.daily_input_tokens?.toLocaleString() ?? '—'}
                </p>
              </div>
              <div className="bg-slate-900/40 rounded-lg p-3">
                <p className="text-xs text-slate-500 mb-1">Output tokens today</p>
                <p className="text-lg font-semibold text-white">
                  {llmUsage.daily_output_tokens?.toLocaleString() ?? '—'}
                </p>
              </div>
            </div>
            <div className="bg-slate-900/40 rounded-lg p-3">
              <p className="text-xs text-slate-500 mb-1">Estimated cost today</p>
              <p className="text-lg font-semibold text-white">
                ${llmUsage.daily_cost_usd?.toFixed(4) ?? '0.0000'}
              </p>
              <CostBar cost={llmUsage.daily_cost_usd} limit={llmUsage.daily_cost_limit_usd} />
            </div>
          </div>
        )}
      </Card>

      {/* Database Counts */}
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <Database size={16} className="text-blue-400" />
          <h3 className="text-sm font-semibold text-white">Database</h3>
        </div>
        {dbCounts ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {Object.entries(dbCounts).map(([table, count]) => (
              <div key={table} className="bg-slate-900/40 rounded-lg p-3">
                <p className="text-xs text-slate-500 mb-1">{table.replace(/_/g, ' ')}</p>
                <p className="text-lg font-semibold text-white">
                  {count == null ? '—' : count.toLocaleString()}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-500 italic">Unable to fetch counts</p>
        )}
      </Card>

      {/* Data Exports */}
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <Download size={16} className="text-slate-400" />
          <h3 className="text-sm font-semibold text-white">Data Export</h3>
        </div>
        <p className="text-xs text-slate-500 mb-4">Download all data tables as CSV for external analysis.</p>
        <div className="flex flex-wrap gap-3">
          <ExportButton href="/api/trades/journal/export" filename="trade_journal.csv">
            Trade Journal
          </ExportButton>
          <ExportButton href="/api/executions/export" filename="execution_logs.csv">
            Execution Logs
          </ExportButton>
          <ExportButton href="/api/trades/export" filename="trades.csv">
            Trades
          </ExportButton>
        </div>
      </Card>
    </div>
  )
}
