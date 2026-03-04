import clsx from 'clsx'

export default function Card({ children, className, title, subtitle, action }) {
  return (
    <div className={clsx('bg-[#1e293b] rounded-xl border border-[#334155] p-5', className)}>
      {(title || action) && (
        <div className="flex items-center justify-between mb-4">
          <div>
            {title && <h3 className="text-sm font-semibold text-white">{title}</h3>}
            {subtitle && <p className="text-xs text-[#64748b] mt-0.5">{subtitle}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </div>
  )
}
