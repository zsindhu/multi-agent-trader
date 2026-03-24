/**
 * PositionHealthBar — visual gauge showing where current price sits
 * relative to strike and break-even for a put or call position.
 */
export default function PositionHealthBar({ currentPrice, strike, breakEven, contractType = 'put' }) {
  if (currentPrice == null || strike == null) {
    return (
      <div className="mt-1.5">
        <div className="h-1.5 bg-slate-800 rounded-full w-full opacity-40" />
      </div>
    )
  }

  const isPut = contractType !== 'call'

  // Determine zone thresholds
  // For puts: danger if current < strike, warning if strike <= current < strike*1.03, safe if >= strike*1.03
  // For calls: danger if current > strike, warning if strike*0.97 < current <= strike, safe if <= strike*0.97
  let zone // 'safe' | 'warning' | 'danger'
  if (isPut) {
    zone = currentPrice < strike ? 'danger' : currentPrice < strike * 1.03 ? 'warning' : 'safe'
  } else {
    zone = currentPrice > strike ? 'danger' : currentPrice > strike * 0.97 ? 'warning' : 'safe'
  }

  const zoneColor = zone === 'safe' ? 'bg-emerald-500' : zone === 'warning' ? 'bg-amber-500' : 'bg-red-500'

  // Build a simple 3-zone bar
  // Range: show from strike*0.90 to strike*1.10
  const low = strike * 0.90
  const high = strike * 1.10
  const range = high - low

  const clamp = (v) => Math.max(0, Math.min(100, ((v - low) / range) * 100))

  const strikePos = clamp(strike)
  const bePos = breakEven != null ? clamp(breakEven) : null
  const currentPos = clamp(currentPrice)

  return (
    <div className="mt-1.5">
      {/* Bar */}
      <div className="relative h-1.5 bg-slate-800 rounded-full w-full">
        {/* Zone fill up to current price */}
        <div
          className={`absolute top-0 left-0 h-full rounded-full transition-all ${zoneColor}`}
          style={{ width: `${currentPos}%` }}
        />
        {/* Strike marker */}
        <div
          className="absolute top-0 w-px h-full bg-slate-400 opacity-60"
          style={{ left: `${strikePos}%` }}
        />
        {/* Break-even marker */}
        {bePos != null && (
          <div
            className="absolute top-0 w-px h-full bg-slate-600"
            style={{ left: `${bePos}%` }}
          />
        )}
      </div>
      {/* Labels */}
      <div className="relative mt-0.5 h-3">
        {bePos != null && (
          <span
            className="absolute text-[9px] text-slate-600 transform -translate-x-1/2"
            style={{ left: `${bePos}%` }}
          >
            BE
          </span>
        )}
        <span
          className="absolute text-[9px] text-slate-500 transform -translate-x-1/2"
          style={{ left: `${strikePos}%` }}
        >
          ${strike}
        </span>
      </div>
    </div>
  )
}
