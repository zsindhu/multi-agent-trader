import { useState, useRef, useEffect } from 'react'

/**
 * Interactive trading mode toggle with dropdown.
 *
 * Paper mode  → green pulse dot + "PAPER TRADING"
 * Live mode   → red pulse dot + "LIVE TRADING" with urgent styling
 *
 * Clicking opens a dropdown to switch modes.
 */
export default function TradingModeToggle({ mode, onSwitch, loading }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  const isLive = mode === 'live'
  const isPaper = mode === 'paper'

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleSelect = (newMode) => {
    setOpen(false)
    if (newMode !== mode) {
      onSwitch(newMode)
    }
  }

  return (
    <div ref={ref} className="relative">
      {/* Toggle button */}
      <button
        onClick={() => setOpen(!open)}
        disabled={loading}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wider transition-all select-none ${
          isLive
            ? 'bg-red-500/15 text-red-300 border border-red-500/40 shadow-[0_0_12px_rgba(239,68,68,0.15)] hover:bg-red-500/25'
            : 'bg-green-500/15 text-green-300 border border-green-500/30 hover:bg-green-500/25'
        } ${loading ? 'opacity-60 cursor-wait' : 'cursor-pointer'}`}
      >
        {/* Pulse dot */}
        <span className="relative flex h-2.5 w-2.5">
          <span
            className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
              isLive ? 'bg-red-400' : 'bg-green-400'
            }`}
          />
          <span
            className={`relative inline-flex rounded-full h-2.5 w-2.5 ${
              isLive ? 'bg-red-500' : 'bg-green-500'
            }`}
          />
        </span>

        <span className={isLive ? 'text-sm' : ''}>
          {loading ? 'Switching…' : isLive ? 'LIVE TRADING' : 'PAPER TRADING'}
        </span>

        {/* Chevron */}
        <svg
          className={`w-3.5 h-3.5 transition-transform ${open ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute right-0 mt-2 w-48 rounded-lg bg-[#1e293b] border border-[#334155] shadow-xl z-50 overflow-hidden">
          {/* Paper option */}
          <button
            onClick={() => handleSelect('paper')}
            className={`w-full flex items-center gap-3 px-4 py-3 text-left text-sm transition-colors ${
              isPaper
                ? 'bg-green-500/10 text-green-300'
                : 'text-slate-300 hover:bg-[#334155]'
            }`}
          >
            <span className="relative flex h-2 w-2">
              <span className={`relative inline-flex rounded-full h-2 w-2 ${isPaper ? 'bg-green-500' : 'bg-slate-500'}`} />
            </span>
            <div>
              <div className="font-medium">Paper Trading</div>
              <div className="text-xs text-slate-500 mt-0.5">Simulated orders</div>
            </div>
            {isPaper && (
              <svg className="w-4 h-4 ml-auto text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            )}
          </button>

          {/* Divider */}
          <div className="border-t border-[#334155]" />

          {/* Live option */}
          <button
            onClick={() => handleSelect('live')}
            className={`w-full flex items-center gap-3 px-4 py-3 text-left text-sm transition-colors ${
              isLive
                ? 'bg-red-500/10 text-red-300'
                : 'text-slate-300 hover:bg-[#334155]'
            }`}
          >
            <span className="relative flex h-2 w-2">
              <span className={`relative inline-flex rounded-full h-2 w-2 ${isLive ? 'bg-red-500' : 'bg-slate-500'}`} />
            </span>
            <div>
              <div className="font-medium">Live Trading</div>
              <div className="text-xs text-slate-500 mt-0.5">Real money</div>
            </div>
            {isLive && (
              <svg className="w-4 h-4 ml-auto text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            )}
          </button>
        </div>
      )}
    </div>
  )
}
