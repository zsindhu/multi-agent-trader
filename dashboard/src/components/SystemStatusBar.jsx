/**
 * SystemStatusBar — sticky top bar showing system health at a glance.
 * Rendered inside App.jsx header, always visible.
 */

function getMarketStatus() {
  // ET offset: UTC-5 (EST) or UTC-4 (EDT)
  const now = new Date()
  const etOffset = (() => {
    // Rough DST check: second Sunday in March through first Sunday in November
    const year = now.getUTCFullYear()
    const dstStart = new Date(Date.UTC(year, 2, 8)) // March 8 approx
    dstStart.setUTCDate(8 + ((7 - dstStart.getUTCDay()) % 7))
    const dstEnd = new Date(Date.UTC(year, 10, 1)) // Nov 1 approx
    dstEnd.setUTCDate(1 + ((7 - dstEnd.getUTCDay()) % 7))
    return now >= dstStart && now < dstEnd ? -4 : -5
  })()
  const etHours = now.getUTCHours() + etOffset
  const etMinutes = now.getUTCMinutes()
  const etTime = etHours * 60 + etMinutes
  const day = now.getUTCDay()
  const isWeekday = day >= 1 && day <= 5

  if (!isWeekday) return { label: 'Closed', color: 'text-slate-400', dot: 'bg-slate-500' }
  if (etTime >= 570 && etTime < 960) return { label: 'Open', color: 'text-emerald-400', dot: 'bg-emerald-500' } // 9:30–16:00
  if (etTime >= 240 && etTime < 570) return { label: 'Pre-market', color: 'text-amber-400', dot: 'bg-amber-500' } // 4:00–9:30
  return { label: 'Closed', color: 'text-slate-400', dot: 'bg-slate-500' }
}

const REGIME_LABEL = {
  risk_on: 'Risk On',
  neutral: 'Neutral',
  risk_off: 'Risk Off',
  crisis: 'Crisis',
}

const REGIME_STYLE = {
  risk_on: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
  neutral: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
  risk_off: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
  crisis: 'bg-red-500/10 text-red-400 border-red-500/30',
}

function relativeTime(isoString) {
  if (!isoString) return null
  const diff = Date.now() - new Date(isoString).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  return `${Math.floor(mins / 60)}h ago`
}

export default function SystemStatusBar({ accountStatus, regime, tradingMode, lastReasoningAt }) {
  const connected = accountStatus?.connection === 'ok'
  const market = getMarketStatus()
  const regimeKey = regime?.regime || 'unknown'
  const regimeStyle = REGIME_STYLE[regimeKey] || 'bg-slate-500/10 text-slate-400 border-slate-500/30'
  const regimeLabel = REGIME_LABEL[regimeKey] || '—'
  const breadth = regime?.breadth_pct
  const vix = regime?.vix_level
  const cycleTime = relativeTime(lastReasoningAt || regime?.updated_at)

  const breadthColor =
    breadth == null ? 'text-slate-500' :
    breadth > 60 ? 'text-emerald-400' :
    breadth < 40 ? 'text-red-400' : 'text-amber-400'

  return (
    <div className="flex items-center gap-3 flex-wrap">
      {/* Connection */}
      <div className="flex items-center gap-1.5">
        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${connected ? 'bg-emerald-500' : 'bg-red-500'}`} />
        <span className={`text-xs font-medium ${connected ? 'text-emerald-400' : 'text-red-400'}`}>
          {connected ? 'Connected' : 'Disconnected'}
        </span>
      </div>

      <span className="text-[#334155] hidden sm:block">·</span>

      {/* Trading mode — hide on mobile */}
      <span className={`hidden sm:inline text-xs font-medium px-1.5 py-0.5 rounded border ${
        tradingMode === 'live'
          ? 'bg-red-500/10 text-red-400 border-red-500/30'
          : 'bg-slate-500/10 text-slate-400 border-slate-500/30'
      }`}>
        {tradingMode === 'live' ? 'Live' : 'Paper'}
      </span>

      {/* Market status — hide on mobile */}
      <div className="hidden sm:flex items-center gap-1">
        <span className={`w-1.5 h-1.5 rounded-full ${market.dot}`} />
        <span className={`text-xs ${market.color}`}>{market.label}</span>
      </div>

      {/* Regime */}
      {regimeKey !== 'unknown' && (
        <span className={`text-xs font-medium px-1.5 py-0.5 rounded border ${regimeStyle}`}>
          {regimeLabel}
        </span>
      )}

      {/* VIX */}
      {vix != null && (
        <span className="text-xs text-slate-400">
          VIX <span className="text-slate-300 font-medium">{vix.toFixed(1)}</span>
        </span>
      )}

      {/* Breadth — hide on mobile */}
      {breadth != null && (
        <span className={`hidden sm:inline text-xs ${breadthColor}`}>
          Breadth {breadth.toFixed(0)}%
        </span>
      )}

      {/* Last cycle — hide on mobile */}
      {cycleTime && (
        <span className="hidden sm:inline text-xs text-slate-500">
          Cycle: {cycleTime}
        </span>
      )}
    </div>
  )
}
