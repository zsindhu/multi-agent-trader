import { memo } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

const REGIME_COLORS = {
  risk_on: '#10b981',
  neutral: '#3b82f6',
  risk_off: '#f59e0b',
  crisis: '#ef4444',
}

const REGIME_LABELS = {
  risk_on: 'Risk On',
  neutral: 'Neutral',
  risk_off: 'Risk Off',
  crisis: 'Crisis',
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs">
      <p className="font-medium text-white mb-1">{REGIME_LABELS[label] || label}</p>
      <p className="text-slate-300">Win rate: <span className="text-white font-medium">{d.win_rate?.toFixed(1)}%</span></p>
      {d.trade_count != null && <p className="text-slate-500">{d.trade_count} trades</p>}
    </div>
  )
}

function RegimeCorrelationChart({ data }) {
  if (!data || data.length === 0) {
    return (
      <p className="text-xs text-slate-600 italic py-4 text-center">
        Not enough trade data yet for regime analysis.
      </p>
    )
  }

  const chartData = data.map(d => ({
    ...d,
    label: REGIME_LABELS[d.regime] || d.regime,
    color: REGIME_COLORS[d.regime] || '#64748b',
  }))

  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={chartData} barSize={32}>
        <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#94a3b8' }} tickLine={false} axisLine={false} />
        <YAxis
          domain={[0, 100]}
          tick={{ fontSize: 10, fill: '#64748b' }}
          tickLine={false}
          axisLine={false}
          tickFormatter={v => `${v}%`}
          width={32}
        />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(148,163,184,0.05)' }} />
        <Bar dataKey="win_rate" radius={[4, 4, 0, 0]}>
          {chartData.map((entry, index) => (
            <Cell key={index} fill={entry.color} fillOpacity={0.85} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export default memo(RegimeCorrelationChart)
