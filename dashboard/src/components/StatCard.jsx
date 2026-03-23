import clsx from 'clsx'

export default function StatCard({ label, value, sub, trend, icon: Icon }) {
  const isPositive = trend === 'up'
  const isNegative = trend === 'down'

  return (
    <div className="bg-[#1e293b] rounded-xl border border-[#334155] p-4 flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-[#64748b] uppercase tracking-wider">
          {label}
        </span>
        {Icon && <Icon size={16} className="text-[#64748b]" />}
      </div>
      <span
        className={clsx(
          'text-xl font-bold',
          isPositive && 'text-[#22c55e]',
          isNegative && 'text-[#ef4444]',
          !isPositive && !isNegative && 'text-white'
        )}
      >
        {value}
      </span>
      {sub && <span className="text-xs text-[#64748b]">{sub}</span>}
    </div>
  )
}
