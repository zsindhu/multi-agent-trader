import Badge from './Badge'

const REGIME_COLOR = {
  risk_on: 'green',
  neutral: 'blue',
  risk_off: 'yellow',
  crisis: 'red',
  unknown: 'gray',
}

const REGIME_LABEL = {
  risk_on: 'Risk On',
  neutral: 'Neutral',
  risk_off: 'Risk Off',
  crisis: 'Crisis',
}

function BreadthBar({ pct }) {
  if (pct == null) return null
  const color = pct > 60 ? 'bg-emerald-500' : pct < 40 ? 'bg-red-500' : 'bg-amber-500'
  const textColor = pct > 60 ? 'text-emerald-400' : pct < 40 ? 'text-red-400' : 'text-amber-400'
  return (
    <div className="mt-1.5">
      <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
        <span>Breadth (% above 50MA)</span>
        <span className={textColor}>{pct.toFixed(0)}%</span>
      </div>
      <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
    </div>
  )
}

function SectorList({ sectors }) {
  if (!sectors || sectors.length === 0) {
    return <p className="text-xs text-slate-600 italic">Sector data not available.</p>
  }
  const sorted = [...sectors].sort((a, b) => (b.return_5d || 0) - (a.return_5d || 0))
  const max = Math.max(...sorted.map(s => Math.abs(s.return_5d || 0)), 1)
  return (
    <div className="space-y-1.5">
      {sorted.map(s => {
        const ret = s.return_5d || 0
        const pct = (Math.abs(ret) / max) * 100
        const color = ret >= 0 ? 'bg-emerald-500' : 'bg-red-500'
        const textColor = ret >= 0 ? 'text-emerald-400' : 'text-red-400'
        return (
          <div key={s.sector} className="flex items-center gap-2">
            <span className="text-xs text-slate-400 w-24 truncate shrink-0">{s.sector}</span>
            <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
            </div>
            <span className={`text-xs font-medium w-12 text-right ${textColor}`}>
              {ret >= 0 ? '+' : ''}{ret.toFixed(1)}%
            </span>
          </div>
        )
      })}
    </div>
  )
}

export default function MarketIntelligence({ regime = {}, earnings = [], recommendations = [], news = [], options = [] }) {
  const heldSymbols = new Set(options.map(o => o.symbol))
  const catalysts = earnings.filter(e => (e.days_until || 99) <= 7)
  const positionEarnings = earnings.filter(e => heldSymbols.has(e.symbol))
  const hasRegime = regime?.regime && regime.regime !== 'unknown'

  return (
    <div className="space-y-4">
      {/* Two-column: Regime + Sectors */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Left: Market Regime */}
        <div className="bg-slate-900/60 rounded-lg p-3 border border-slate-800">
          <p className="text-xs font-medium text-slate-400 mb-2">Market Regime</p>
          {!hasRegime ? (
            <p className="text-xs text-slate-600 italic">Market regime data not available — Phase A services not configured.</p>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Badge variant={REGIME_COLOR[regime.regime] || 'gray'}>
                  {REGIME_LABEL[regime.regime] || regime.regime}
                </Badge>
                {regime.confidence_score != null && (
                  <span className="text-xs text-slate-500">{(regime.confidence_score * 100).toFixed(0)}% conf.</span>
                )}
              </div>
              {regime.summary && (
                <p className="text-xs text-slate-400 leading-relaxed">{regime.summary}</p>
              )}
              <BreadthBar pct={regime.breadth_pct} />
              <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs mt-1">
                {regime.vix_level != null && (
                  <>
                    <span className="text-slate-500">VIX</span>
                    <span className="text-slate-300">{regime.vix_level.toFixed(1)}</span>
                  </>
                )}
                {regime.spy_trend && (
                  <>
                    <span className="text-slate-500">SPY trend</span>
                    <span className="text-slate-300 capitalize">{regime.spy_trend.replace('_', ' ')}</span>
                  </>
                )}
                {regime.credit_stress != null && (
                  <>
                    <span className="text-slate-500">Credit stress</span>
                    <span className={regime.credit_stress ? 'text-red-400' : 'text-emerald-400'}>
                      {regime.credit_stress ? 'Yes' : 'No'}
                    </span>
                  </>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Right: Sector Rotation */}
        <div className="bg-slate-900/60 rounded-lg p-3 border border-slate-800">
          <p className="text-xs font-medium text-slate-400 mb-2">Sector Rotation (5d)</p>
          <SectorList sectors={regime.sectors} />
        </div>
      </div>

      {/* Upcoming Catalysts */}
      {(catalysts.length > 0 || positionEarnings.length > 0) && (
        <div>
          <p className="text-xs font-medium text-slate-400 mb-1.5">Upcoming Catalysts</p>
          <div className="space-y-1">
            {[...new Map([...positionEarnings, ...catalysts].map(e => [e.symbol, e])).values()].map(e => (
              <div
                key={e.symbol}
                className={`flex items-center gap-2 text-xs px-3 py-1.5 rounded-lg border ${
                  heldSymbols.has(e.symbol)
                    ? 'bg-amber-500/10 border-amber-500/20'
                    : 'bg-slate-800/40 border-slate-700/40'
                }`}
              >
                <span className={`font-medium ${heldSymbols.has(e.symbol) ? 'text-amber-400' : 'text-slate-300'}`}>
                  {e.symbol}
                </span>
                <span className="text-slate-500">earnings in {e.days_until}d</span>
                <Badge variant={e.risk_level === 'high_risk' ? 'red' : 'yellow'}>
                  {e.risk_level === 'high_risk' ? 'High Risk' : 'Approaching'}
                </Badge>
                {heldSymbols.has(e.symbol) && (
                  <span className="text-amber-500 text-[10px] font-medium">⚠ HELD</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Performance Insights */}
      {recommendations.length > 0 && recommendations[0] !== 'Not enough closed trade data for recommendations yet.' && (
        <div>
          <p className="text-xs font-medium text-slate-400 mb-1.5">Performance Insights</p>
          <div className="space-y-1">
            {recommendations.map((rec, i) => (
              <p key={i} className="text-xs text-slate-500 pl-3 border-l border-slate-700">{rec}</p>
            ))}
          </div>
        </div>
      )}

      {/* Market Headlines */}
      {news.length > 0 && (
        <div>
          <p className="text-xs font-medium text-slate-400 mb-1.5">Market Headlines</p>
          <div className="space-y-1">
            {news.slice(0, 5).map((n, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <span className="text-slate-600 shrink-0 mt-0.5">{n.source}</span>
                <span className="text-slate-400 leading-snug">{n.headline}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
