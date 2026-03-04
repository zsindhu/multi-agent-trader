import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import Badge from './Badge'

/**
 * Maps agent name → display label, badge color, and accent dot color.
 */
const AGENT_META = {
  'Covered-Calls':      { label: 'Covered Calls',      badge: 'indigo', dot: 'bg-indigo-400' },
  'Cash-Secured-Puts':  { label: 'Cash Secured Puts',  badge: 'green',  dot: 'bg-emerald-400' },
  'Wheel':              { label: 'The Wheel',           badge: 'pink',   dot: 'bg-pink-400' },
}

/**
 * Infer the Wheel phase from the contracts it manages.
 * If the Wheel agent has short puts → selling puts.
 * If it has short calls → selling calls.
 */
function inferWheelPhase(contracts) {
  const hasPut = contracts.some((c) => c.contract_type === 'put')
  const hasCall = contracts.some((c) => c.contract_type === 'call')
  if (hasCall) return 'selling calls'
  if (hasPut) return 'selling puts'
  return null
}

const fmt = (n) => {
  if (n == null) return '—'
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 })
}

/**
 * Group raw options by underlying symbol and aggregate.
 *
 * Returns: [{ symbol, contracts, agent, agentRaw, premium, pnl, wheelPhase? }]
 */
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

    // Use the first non-empty assigned_to as the agent
    if (!map[sym].agent && o.assigned_to) {
      map[sym].agent = o.assigned_to
    }
  }

  return Object.values(map).map((g) => {
    const meta = AGENT_META[g.agent] || { label: g.agent || 'Unassigned', badge: 'gray', dot: 'bg-slate-400' }
    const wheelPhase = g.agent === 'Wheel' ? inferWheelPhase(g.items) : null
    const agentLabel = wheelPhase ? `${meta.label} (${wheelPhase})` : meta.label

    return {
      symbol: g.symbol,
      contracts: g.items.reduce((sum, i) => sum + Math.abs(i.quantity), 0),
      agentLabel,
      agentBadge: meta.badge,
      premium: g.totalPremium,
      pnl: g.totalPnl,
    }
  })
}

/**
 * ActivePositions — collapsible glanceable summary of open option positions,
 * grouped by underlying.
 */
export default function ActivePositions({ options = [] }) {
  const [expanded, setExpanded] = useState(true)

  const grouped = groupByUnderlying(options)
  const totalContracts = grouped.reduce((s, g) => s + g.contracts, 0)
  const totalUnderlyings = grouped.length

  if (totalContracts === 0) return null // nothing to show

  return (
    <div className="bg-[#1e293b] rounded-xl border border-[#334155] overflow-hidden">
      {/* Header — always visible */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-[#334155]/30 transition-colors"
      >
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-white tracking-wide uppercase">
            Active Positions
          </h3>
          <span className="text-xs text-[#64748b]">
            {totalContracts} contract{totalContracts !== 1 ? 's' : ''} across{' '}
            {totalUnderlyings} underlying{totalUnderlyings !== 1 ? 's' : ''}
          </span>
        </div>
        <ChevronDown
          size={16}
          className={`text-[#64748b] transition-transform duration-200 ${
            expanded ? 'rotate-180' : ''
          }`}
        />
      </button>

      {/* Body — collapsible */}
      <div
        className={`transition-all duration-200 ease-in-out overflow-hidden ${
          expanded ? 'max-h-[600px] opacity-100' : 'max-h-0 opacity-0'
        }`}
      >
        <div className="px-5 pb-4 space-y-1.5">
          {grouped.map((row) => {
            const pnlColor =
              row.pnl > 0.5 ? 'text-emerald-400' :
              row.pnl < -0.5 ? 'text-red-400' : 'text-[#64748b]'

            return (
              <div
                key={row.symbol}
                className="flex items-center gap-4 py-2.5 px-3 rounded-lg hover:bg-[#334155]/30 transition-colors"
              >
                {/* Symbol */}
                <span className="text-sm font-semibold text-white w-16">
                  {row.symbol}
                </span>

                {/* Contracts count */}
                <span className="text-xs text-[#94a3b8] w-20">
                  {row.contracts} contract{row.contracts !== 1 ? 's' : ''}
                </span>

                {/* Agent badge */}
                <Badge variant={row.agentBadge}>
                  {row.agentLabel}
                </Badge>

                {/* Spacer */}
                <div className="flex-1" />

                {/* Premium */}
                <div className="text-right w-24">
                  <p className="text-xs text-[#64748b]">Premium</p>
                  <p className="text-sm font-medium text-[#94a3b8]">{fmt(row.premium)}</p>
                </div>

                {/* P&L */}
                <div className="text-right w-24">
                  <p className="text-xs text-[#64748b]">P&L</p>
                  <p className={`text-sm font-medium ${pnlColor}`}>{fmt(row.pnl)}</p>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
