import { memo, useState } from 'react'
import { ChevronUp, ChevronDown } from 'lucide-react'

const fmt = (n) =>
  n == null ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 })

const fmtPct = (n) => (n == null ? '—' : `${n.toFixed(1)}%`)

const COLUMNS = [
  { key: 'symbol', label: 'Symbol', align: 'left' },
  { key: 'total_trades', label: 'Trades', align: 'right' },
  { key: 'win_rate', label: 'Win Rate', align: 'right', fmt: fmtPct },
  { key: 'total_pnl', label: 'Total P&L', align: 'right', fmt: fmt },
  { key: 'avg_premium', label: 'Avg Premium', align: 'right', fmt: fmt },
  { key: 'last_traded', label: 'Last Trade', align: 'right' },
]

function SymbolScorecard({ data }) {
  const [sortKey, setSortKey] = useState('total_pnl')
  const [sortDir, setSortDir] = useState('desc')

  if (!data || data.length === 0) {
    return (
      <p className="text-xs text-slate-600 italic py-4 text-center">
        No closed trades recorded yet.
      </p>
    )
  }

  const sorted = [...data].sort((a, b) => {
    const av = a[sortKey] ?? (typeof a[sortKey] === 'number' ? 0 : '')
    const bv = b[sortKey] ?? (typeof b[sortKey] === 'number' ? 0 : '')
    if (av < bv) return sortDir === 'asc' ? -1 : 1
    if (av > bv) return sortDir === 'asc' ? 1 : -1
    return 0
  })

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-slate-800">
            {COLUMNS.map(col => (
              <th
                key={col.key}
                className={`pb-2 font-medium text-slate-500 cursor-pointer hover:text-slate-300 select-none ${col.align === 'right' ? 'text-right' : 'text-left'}`}
                onClick={() => handleSort(col.key)}
              >
                <span className="inline-flex items-center gap-0.5">
                  {col.label}
                  {sortKey === col.key && (
                    sortDir === 'asc'
                      ? <ChevronUp size={10} className="text-blue-400" />
                      : <ChevronDown size={10} className="text-blue-400" />
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map(row => {
            const pnl = row.total_pnl ?? 0
            const rowTint = pnl > 0 ? 'hover:bg-emerald-500/5' : pnl < 0 ? 'hover:bg-red-500/5' : 'hover:bg-slate-800/30'
            return (
              <tr key={row.symbol} className={`border-b border-slate-800/50 transition-colors ${rowTint}`}>
                <td className="py-2 font-medium text-white">{row.symbol}</td>
                <td className="py-2 text-right text-slate-300">{row.total_trades ?? '—'}</td>
                <td className="py-2 text-right">
                  <span className={`font-medium ${(row.win_rate ?? 0) >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {fmtPct(row.win_rate)}
                  </span>
                </td>
                <td className={`py-2 text-right font-medium ${pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {fmt(row.total_pnl)}
                </td>
                <td className="py-2 text-right text-slate-400">{fmt(row.avg_premium)}</td>
                <td className="py-2 text-right text-slate-500">
                  {row.last_traded ? new Date(row.last_traded).toLocaleDateString() : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default memo(SymbolScorecard)
