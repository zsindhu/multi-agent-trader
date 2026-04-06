import { useState } from 'react'
import { ChevronDown, AlertTriangle } from 'lucide-react'
import Badge from './Badge'
import PositionHealthBar from './PositionHealthBar'

/**
 * Maps agent name → display label, badge color, and accent dot color.
 */
const AGENT_META = {
  'Covered-Calls':      { label: 'CC',   badge: 'indigo', dot: 'bg-indigo-400' },
  'Cash-Secured-Puts':  { label: 'CSP',  badge: 'green',  dot: 'bg-emerald-400' },
  'Wheel':              { label: 'Wheel', badge: 'pink',   dot: 'bg-pink-400' },
}
const UNASSIGNED_META = { label: 'Unassigned', badge: 'red', dot: 'bg-red-400' }

function inferWheelPhase(contracts) {
  const hasCall = contracts.some((c) => c.contract_type === 'call')
  if (hasCall) return 'CC'
  return 'CSP'
}

const fmt = (n) => {
  if (n == null) return '—'
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 })
}

function dte(expiryDate) {
  if (!expiryDate) return null
  const diff = new Date(expiryDate + 'T00:00:00') - new Date()
  return Math.max(0, Math.ceil(diff / 86400000))
}

function groupByUnderlying(options) {
  const map = {}
  for (const o of options) {
    const sym = o.symbol
    if (!map[sym]) {
      map[sym] = { symbol: sym, items: [], totalPremium: 0, totalPnl: 0, agent: '' }
    }
    map[sym].items.push(o)
    map[sym].totalPremium += o.premium_collected || 0
    map[sym].totalPnl += o.pnl || 0
    if (!map[sym].agent && o.assigned_to) {
      map[sym].agent = o.assigned_to
    }
  }

  return Object.values(map).map((g) => {
    const isWheel = g.agent === 'Wheel'
    const wheelVariant = isWheel ? inferWheelPhase(g.items) : null
    const meta = g.agent
      ? (AGENT_META[g.agent] || { label: g.agent, badge: 'gray', dot: 'bg-slate-400' })
      : UNASSIGNED_META
    const badgeLabel = isWheel ? `Wheel (${wheelVariant})` : meta.label

    return {
      symbol: g.symbol,
      items: g.items,
      contracts: g.items.reduce((sum, i) => sum + Math.abs(i.quantity), 0),
      agentLabel: badgeLabel,
      agentBadge: meta.badge,
      premium: g.totalPremium,
      pnl: g.totalPnl,
    }
  })
}

function earningsWarning(symbol, earnings) {
  if (!earnings?.length) return null
  const ev = earnings.find(e => e.symbol === symbol)
  if (!ev) return null
  return ev
}

/**
 * ActivePositions — collapsible summary of open option positions grouped by underlying.
 * Enhanced with DTE, earnings flags, and PositionHealthBar.
 */
export default function ActivePositions({ options = [], earnings = [] }) {
  const [expanded, setExpanded] = useState(true)

  const grouped = groupByUnderlying(options)
  const totalContracts = grouped.reduce((s, g) => s + g.contracts, 0)

  if (totalContracts === 0) return null

  return (
    <div className="bg-[#1e293b] rounded-xl border border-[#334155] overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-[#334155]/30 transition-colors"
      >
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-white tracking-wide uppercase">
            Active Positions
          </h3>
          <span className="text-xs text-[#64748b]">
            {totalContracts} contract{totalContracts !== 1 ? 's' : ''} · {grouped.length} underlying{grouped.length !== 1 ? 's' : ''}
          </span>
        </div>
        <ChevronDown
          size={16}
          className={`text-[#64748b] transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
        />
      </button>

      <div className={`transition-all duration-200 ease-in-out overflow-hidden ${expanded ? 'max-h-[800px] opacity-100' : 'max-h-0 opacity-0'}`}>
        <div className="px-5 pb-4 space-y-2">
          {grouped.map((row) => {
            const pnlColor = row.pnl > 0.5 ? 'text-emerald-400' : row.pnl < -0.5 ? 'text-red-400' : 'text-[#64748b]'
            const earningsAlert = earningsWarning(row.symbol, earnings)

            // For health bar: use first contract's data
            const firstContract = row.items[0]
            const contractType = firstContract?.contract_type || 'put'
            const strike = firstContract?.strike
            const currentPrice = firstContract?.current_price
            const breakEven = firstContract?.break_even_price
            const expiry = firstContract?.expiration
            const daysToExpiry = dte(expiry)

            return (
              <div key={row.symbol} className="py-2.5 px-3 rounded-lg hover:bg-[#334155]/20 transition-colors border border-transparent hover:border-[#334155]/40">
                {/* Top row */}
                <div className="flex items-center gap-3">
                  {/* Symbol */}
                  <span className="text-sm font-semibold text-white w-14 shrink-0">{row.symbol}</span>

                  {/* Strategy badge */}
                  <Badge variant={row.agentBadge}>{row.agentLabel}</Badge>

                  {/* Strike + expiry */}
                  {strike && (
                    <span className="text-xs text-slate-400 hidden sm:inline">
                      ${strike.toFixed(0)}{contractType === 'put' ? 'P' : 'C'}
                      {expiry && ` exp ${new Date(expiry + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`}
                    </span>
                  )}

                  {/* DTE */}
                  {daysToExpiry != null && (
                    <span className={`text-xs hidden sm:inline font-medium ${daysToExpiry <= 7 ? 'text-amber-400' : 'text-slate-500'}`}>
                      {daysToExpiry}d
                    </span>
                  )}

                  {/* Earnings warning */}
                  {earningsAlert && (
                    <span
                      className="text-amber-400 flex items-center gap-1 text-xs"
                      title={`Earnings in ${earningsAlert.days_until} days (${earningsAlert.event_date})`}
                    >
                      <AlertTriangle size={12} />
                      <span className="hidden sm:inline">{earningsAlert.days_until}d</span>
                    </span>
                  )}

                  <div className="flex-1" />

                  {/* P&L */}
                  <div className="text-right w-20 shrink-0">
                    <p className="text-[10px] text-[#64748b]">P&L</p>
                    <p className={`text-sm font-medium ${pnlColor}`}>{fmt(row.pnl)}</p>
                  </div>

                  {/* Premium */}
                  <div className="text-right w-20 shrink-0 hidden sm:block">
                    <p className="text-[10px] text-[#64748b]">Premium</p>
                    <p className="text-sm font-medium text-[#94a3b8]">{fmt(row.premium)}</p>
                  </div>
                </div>

                {/* Per-contract agent assignments (when multiple contracts) */}
                {row.items.length > 1 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {row.items.map((c, i) => {
                      const cMeta = c.assigned_to
                        ? (AGENT_META[c.assigned_to] || { label: c.assigned_to, badge: 'gray' })
                        : UNASSIGNED_META
                      return (
                        <span key={i} className="text-[10px] text-slate-500">
                          <Badge variant={cMeta.badge}>{cMeta.label}</Badge>
                          {' '}{c.contract_type === 'put' ? 'P' : 'C'} ${c.strike?.toFixed(0)}
                        </span>
                      )
                    })}
                  </div>
                )}

                {/* Health bar */}
                {(currentPrice != null || strike != null) && (
                  <PositionHealthBar
                    currentPrice={currentPrice}
                    strike={strike}
                    breakEven={breakEven}
                    contractType={contractType}
                  />
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
