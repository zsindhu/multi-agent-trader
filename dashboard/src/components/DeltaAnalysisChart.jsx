import { memo } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs">
      <p className="font-medium text-white mb-1">Delta {label}</p>
      <p className="text-slate-300">Win rate: <span className="text-white font-medium">{d.win_rate?.toFixed(1)}%</span></p>
      {d.avg_return != null && (
        <p className="text-slate-300">Avg return: <span className="text-emerald-400 font-medium">{d.avg_return?.toFixed(1)}%</span></p>
      )}
      {d.trade_count != null && <p className="text-slate-500">{d.trade_count} trades</p>}
    </div>
  )
}

function DeltaAnalysisChart({ data }) {
  if (!data || !Array.isArray(data) || data.length === 0) {
    return (
      <p className="text-xs text-slate-600 italic py-4 text-center">
        Need at least 10 closed trades for delta analysis.
      </p>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={data} barSize={28}>
        <XAxis dataKey="delta_bucket" tick={{ fontSize: 11, fill: '#94a3b8' }} tickLine={false} axisLine={false} />
        <YAxis
          domain={[0, 100]}
          tick={{ fontSize: 10, fill: '#64748b' }}
          tickLine={false}
          axisLine={false}
          tickFormatter={v => `${v}%`}
          width={32}
        />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(148,163,184,0.05)' }} />
        <Bar dataKey="win_rate" fill="#6366f1" fillOpacity={0.85} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

export default memo(DeltaAnalysisChart)
