import { useEffect, useState } from 'react'
import { Briefcase, ArrowDownRight, ArrowUpRight } from 'lucide-react'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Spinner from '../components/Spinner'
import { fetchPortfolio } from '../api'

const fmt = (n) => n == null ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 })
const pctFmt = (n) => n == null ? '—' : `${n >= 0 ? '+' : ''}${n.toFixed(1)}%`

export default function Positions() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState('stocks')

  useEffect(() => {
    fetchPortfolio()
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Spinner />

  const positions = data?.positions || []
  const options = data?.options || []

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-white flex items-center gap-2">
        <Briefcase size={24} /> Active Positions
      </h2>

      {/* Tab toggle */}
      <div className="flex gap-2">
        {['stocks', 'options'].map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm rounded-lg transition-colors ${
              tab === t
                ? 'bg-blue-600 text-white'
                : 'bg-[#1e293b] text-[#94a3b8] hover:text-white border border-[#334155]'
            }`}
          >
            {t === 'stocks' ? `Stocks (${positions.length})` : `Options (${options.length})`}
          </button>
        ))}
      </div>

      {/* Stocks Table */}
      {tab === 'stocks' && (
        <Card>
          {positions.length === 0 ? (
            <p className="text-sm text-[#64748b] text-center py-8">No stock positions</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[#64748b] text-xs uppercase border-b border-[#334155]">
                    <th className="text-left py-3 px-2">Symbol</th>
                    <th className="text-right py-3 px-2">Shares</th>
                    <th className="text-right py-3 px-2">Avg Cost</th>
                    <th className="text-right py-3 px-2">Price</th>
                    <th className="text-right py-3 px-2">Mkt Value</th>
                    <th className="text-right py-3 px-2">P&L</th>
                    <th className="text-left py-3 px-2">Agent</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => (
                    <tr key={p.symbol} className="border-b border-[#334155]/50 hover:bg-[#334155]/30">
                      <td className="py-3 px-2 font-medium text-white">{p.symbol}</td>
                      <td className="py-3 px-2 text-right">{p.quantity}</td>
                      <td className="py-3 px-2 text-right">{fmt(p.avg_cost)}</td>
                      <td className="py-3 px-2 text-right">{fmt(p.current_price)}</td>
                      <td className="py-3 px-2 text-right">{fmt(p.market_value)}</td>
                      <td className={`py-3 px-2 text-right font-medium ${p.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {fmt(p.unrealized_pnl)}
                      </td>
                      <td className="py-3 px-2">
                        {p.assigned_to ? <Badge variant="blue">{p.assigned_to}</Badge> : <span className="text-[#64748b]">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {/* Options Table */}
      {tab === 'options' && (
        <Card>
          {options.length === 0 ? (
            <p className="text-sm text-[#64748b] text-center py-8">No option positions</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[#64748b] text-xs uppercase border-b border-[#334155]">
                    <th className="text-left py-3 px-2">Symbol</th>
                    <th className="text-left py-3 px-2">Type</th>
                    <th className="text-right py-3 px-2">Strike</th>
                    <th className="text-left py-3 px-2">Exp</th>
                    <th className="text-right py-3 px-2">Qty</th>
                    <th className="text-right py-3 px-2">Entry</th>
                    <th className="text-right py-3 px-2">Current</th>
                    <th className="text-right py-3 px-2">P&L</th>
                    <th className="text-right py-3 px-2">P&L%</th>
                    <th className="text-left py-3 px-2">Agent</th>
                  </tr>
                </thead>
                <tbody>
                  {options.map((o, i) => (
                    <tr key={i} className="border-b border-[#334155]/50 hover:bg-[#334155]/30">
                      <td className="py-3 px-2 font-medium text-white">{o.symbol}</td>
                      <td className="py-3 px-2">
                        <Badge variant={o.contract_type === 'put' ? 'red' : 'green'}>
                          {o.is_short ? 'Short' : 'Long'} {o.contract_type}
                        </Badge>
                      </td>
                      <td className="py-3 px-2 text-right">{fmt(o.strike)}</td>
                      <td className="py-3 px-2">{o.expiration}</td>
                      <td className="py-3 px-2 text-right">{o.quantity}</td>
                      <td className="py-3 px-2 text-right">{fmt(o.entry_price)}</td>
                      <td className="py-3 px-2 text-right">{fmt(o.current_price)}</td>
                      <td className={`py-3 px-2 text-right font-medium ${o.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {fmt(o.pnl)}
                      </td>
                      <td className={`py-3 px-2 text-right ${o.pnl_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {pctFmt(o.pnl_pct)}
                      </td>
                      <td className="py-3 px-2">
                        {o.assigned_to ? <Badge variant="blue">{o.assigned_to}</Badge> : <span className="text-[#64748b]">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </div>
  )
}
