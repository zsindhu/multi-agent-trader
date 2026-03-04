import { useEffect, useState } from 'react'
import { ScrollText, Filter } from 'lucide-react'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Spinner from '../components/Spinner'
import { fetchTradeHistory, fetchJournal } from '../api'

const fmt = (n) => n == null ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 })

export default function TradeHistory() {
  const [tab, setTab] = useState('trades')
  const [trades, setTrades] = useState([])
  const [journal, setJournal] = useState([])
  const [loading, setLoading] = useState(true)
  const [agentFilter, setAgentFilter] = useState('')
  const [symbolFilter, setSymbolFilter] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const params = {}
      if (agentFilter) params.agent = agentFilter
      if (symbolFilter) params.symbol = symbolFilter.toUpperCase()
      params.limit = 100

      if (tab === 'trades') {
        const data = await fetchTradeHistory(params)
        setTrades(data.trades || [])
      } else {
        const data = await fetchJournal(params)
        setJournal(data.entries || [])
      }
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [tab, agentFilter, symbolFilter])

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-white flex items-center gap-2">
        <ScrollText size={24} /> Trade History
      </h2>

      {/* Controls */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="flex gap-2">
          {['trades', 'journal'].map((t) => (
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

        <div className="flex gap-2 ml-auto">
          <select
            value={agentFilter}
            onChange={(e) => setAgentFilter(e.target.value)}
            className="bg-[#1e293b] border border-[#334155] rounded-lg px-3 py-2 text-sm text-[#94a3b8] focus:outline-none focus:border-blue-500"
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
            onChange={(e) => setSymbolFilter(e.target.value)}
            className="bg-[#1e293b] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white placeholder-[#64748b] w-28 focus:outline-none focus:border-blue-500"
          />
        </div>
      </div>

      {loading ? (
        <Spinner />
      ) : tab === 'trades' ? (
        <Card>
          {trades.length === 0 ? (
            <p className="text-sm text-[#64748b] text-center py-8">No trades found</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[#64748b] text-xs uppercase border-b border-[#334155]">
                    <th className="text-left py-3 px-2">Date</th>
                    <th className="text-left py-3 px-2">Agent</th>
                    <th className="text-left py-3 px-2">Symbol</th>
                    <th className="text-left py-3 px-2">Type</th>
                    <th className="text-left py-3 px-2">Side</th>
                    <th className="text-right py-3 px-2">Qty</th>
                    <th className="text-right py-3 px-2">Price</th>
                    <th className="text-right py-3 px-2">Premium</th>
                    <th className="text-right py-3 px-2">P&L</th>
                    <th className="text-left py-3 px-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((t) => (
                    <tr key={t.id} className="border-b border-[#334155]/50 hover:bg-[#334155]/30">
                      <td className="py-3 px-2 text-[#94a3b8] text-xs">
                        {t.created_at ? new Date(t.created_at).toLocaleDateString() : '—'}
                      </td>
                      <td className="py-3 px-2"><Badge variant="blue">{t.agent_name}</Badge></td>
                      <td className="py-3 px-2 font-medium text-white">{t.symbol}</td>
                      <td className="py-3 px-2">{t.trade_type}</td>
                      <td className="py-3 px-2">
                        <Badge variant={t.side === 'sell' ? 'red' : 'green'}>{t.side}</Badge>
                      </td>
                      <td className="py-3 px-2 text-right">{t.quantity}</td>
                      <td className="py-3 px-2 text-right">{fmt(t.price)}</td>
                      <td className="py-3 px-2 text-right">{fmt(t.premium)}</td>
                      <td className={`py-3 px-2 text-right font-medium ${t.pnl != null ? (t.pnl >= 0 ? 'text-emerald-400' : 'text-red-400') : 'text-[#64748b]'}`}>
                        {fmt(t.pnl)}
                      </td>
                      <td className="py-3 px-2">
                        <Badge variant={t.status === 'filled' ? 'green' : 'gray'}>{t.status}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      ) : (
        /* Journal view */
        <Card>
          {journal.length === 0 ? (
            <p className="text-sm text-[#64748b] text-center py-8">No journal entries</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[#64748b] text-xs uppercase border-b border-[#334155]">
                    <th className="text-left py-3 px-2">Entry</th>
                    <th className="text-left py-3 px-2">Agent</th>
                    <th className="text-left py-3 px-2">Symbol</th>
                    <th className="text-left py-3 px-2">Type</th>
                    <th className="text-right py-3 px-2">Strike</th>
                    <th className="text-right py-3 px-2">Delta</th>
                    <th className="text-right py-3 px-2">DTE</th>
                    <th className="text-right py-3 px-2">IV Rank</th>
                    <th className="text-right py-3 px-2">P&L</th>
                    <th className="text-left py-3 px-2">Exit Reason</th>
                    <th className="text-right py-3 px-2">Days</th>
                  </tr>
                </thead>
                <tbody>
                  {journal.map((e) => (
                    <tr key={e.id} className="border-b border-[#334155]/50 hover:bg-[#334155]/30">
                      <td className="py-3 px-2 text-[#94a3b8] text-xs">
                        {e.entry_at ? new Date(e.entry_at).toLocaleDateString() : '—'}
                      </td>
                      <td className="py-3 px-2"><Badge variant="blue">{e.agent_name}</Badge></td>
                      <td className="py-3 px-2 font-medium text-white">{e.symbol}</td>
                      <td className="py-3 px-2">
                        <Badge variant={e.contract_type === 'put' ? 'red' : 'green'}>
                          {e.side} {e.contract_type}
                        </Badge>
                      </td>
                      <td className="py-3 px-2 text-right">{fmt(e.strike)}</td>
                      <td className="py-3 px-2 text-right">{e.delta_at_entry?.toFixed(2) ?? '—'}</td>
                      <td className="py-3 px-2 text-right">{e.dte_at_entry ?? '—'}</td>
                      <td className="py-3 px-2 text-right">{e.entry_iv_rank?.toFixed(0) ?? '—'}</td>
                      <td className={`py-3 px-2 text-right font-medium ${e.realized_pnl != null ? (e.realized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400') : 'text-[#64748b]'}`}>
                        {fmt(e.realized_pnl)}
                      </td>
                      <td className="py-3 px-2">
                        {e.exit_reason ? <Badge variant="gray">{e.exit_reason}</Badge> : <span className="text-[#64748b]">Open</span>}
                      </td>
                      <td className="py-3 px-2 text-right">{e.days_held ?? '—'}</td>
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
