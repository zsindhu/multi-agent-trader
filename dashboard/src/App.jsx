import { useState, useEffect } from 'react'
import { Routes, Route, NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Crosshair,
  BarChart2,
} from 'lucide-react'
import DashboardPage from './pages/DashboardPage'
import TradeDeskPage from './pages/TradeDeskPage'
import PerformancePage from './pages/PerformancePage'
import TradingModeToggle from './components/TradingModeToggle'
import ConfirmLiveModal from './components/ConfirmLiveModal'
import { fetchTradingMode, updateTradingMode, fetchAccountStatus } from './api'

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/trade-desk', icon: Crosshair, label: 'Trade Desk' },
  { to: '/performance', icon: BarChart2, label: 'Performance' },
]

/**
 * Small connection status indicator for the header bar.
 * Shows Alpaca connection health and options trading level at a glance.
 */
function AlpacaStatusBadge({ status }) {
  if (!status) return null

  const connected = status.connection === 'ok'
  const optionsOk = status.options_enabled
  const level = status.options_level
  const warnings = status.warnings || []

  // Determine overall health colour
  const healthy = connected && optionsOk
  const degraded = connected && !optionsOk

  const dotColor = healthy
    ? 'bg-emerald-500'
    : degraded
    ? 'bg-amber-500'
    : 'bg-red-500'

  const label = !connected
    ? 'Alpaca: disconnected'
    : !optionsOk
    ? `Options: level ${level ?? 'none'}`
    : `Options L${level}`

  const textColor = healthy
    ? 'text-emerald-400'
    : degraded
    ? 'text-amber-400'
    : 'text-red-400'

  const borderColor = healthy
    ? 'border-emerald-500/20'
    : degraded
    ? 'border-amber-500/20'
    : 'border-red-500/20'

  const bgColor = healthy
    ? 'bg-emerald-500/5'
    : degraded
    ? 'bg-amber-500/5'
    : 'bg-red-500/5'

  return (
    <div className="relative group">
      <div className={`flex items-center gap-1.5 px-2 py-1 rounded-md border text-xs ${bgColor} ${borderColor} ${textColor} cursor-default select-none`}>
        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotColor}`} />
        <span className="font-medium">{label}</span>
      </div>

      {/* Tooltip on hover */}
      {warnings.length > 0 && (
        <div className="absolute right-0 top-full mt-1.5 w-72 bg-[#1e293b] border border-[#334155] rounded-lg shadow-xl z-50 p-3 hidden group-hover:block">
          <p className="text-xs font-semibold text-white mb-2">Account Warnings</p>
          {warnings.map((w, i) => (
            <p key={i} className="text-xs text-amber-300 leading-relaxed mb-1 last:mb-0">{w}</p>
          ))}
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [tradingMode, setTradingMode] = useState('paper')
  const [modeLoading, setModeLoading] = useState(false)
  const [showLiveConfirm, setShowLiveConfirm] = useState(false)
  const [accountStatus, setAccountStatus] = useState(null)

  const isLive = tradingMode === 'live'

  // Fetch current trading mode and account status on mount
  useEffect(() => {
    fetchTradingMode()
      .then((data) => setTradingMode(data.trading_mode))
      .catch(() => setTradingMode('paper'))
    fetchAccountStatus()
      .then(setAccountStatus)
      .catch(() => setAccountStatus({ connection: 'failed', options_enabled: false, warnings: [] }))
  }, [])

  // Handle mode switch request from toggle
  const handleModeSwitch = (newMode) => {
    if (newMode === 'live') {
      // Require confirmation before switching to live
      setShowLiveConfirm(true)
    } else {
      // Switching to paper — always safe, no confirmation needed
      doSwitch('paper')
    }
  }

  // Actually perform the switch (after confirmation if needed)
  const doSwitch = async (newMode) => {
    setModeLoading(true)
    setShowLiveConfirm(false)
    try {
      const result = await updateTradingMode(newMode)
      setTradingMode(result.trading_mode)
      // Force a page-level data refresh since account balances changed
      window.dispatchEvent(new CustomEvent('trading-mode-changed', { detail: result }))
      // Refresh account status for the new mode
      fetchAccountStatus().then(setAccountStatus).catch(() => {})
    } catch (err) {
      console.error('Failed to switch trading mode:', err)
      alert(`Failed to switch mode: ${err.message}`)
    } finally {
      setModeLoading(false)
    }
  }

  return (
    <div className="flex h-screen">
      {/* ── Live-mode top border accent ───────────────────────────── */}
      {isLive && (
        <div className="fixed top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-red-600 via-red-500 to-red-600 z-50" />
      )}

      {/* ── Sidebar ──────────────────────────────────────────────── */}
      <aside
        className={`w-56 flex-shrink-0 border-r flex flex-col transition-colors duration-300 ${
          isLive
            ? 'bg-[#1e293b] border-red-500/20'
            : 'bg-[#1e293b] border-[#334155]'
        }`}
      >
        <div className={`px-5 py-5 border-b ${isLive ? 'border-red-500/20' : 'border-[#334155]'}`}>
          <h1 className="text-lg font-bold tracking-tight text-white">
            ⚡ Premium Trader
          </h1>
          <p className="text-xs text-[#64748b] mt-0.5">Multi-Agent Options</p>
        </div>
        <nav className="flex-1 py-3">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-5 py-2.5 text-sm transition-colors ${
                  isActive
                    ? `bg-[#334155] text-white font-medium border-r-2 ${isLive ? 'border-red-500' : 'border-blue-500'}`
                    : 'text-[#94a3b8] hover:text-white hover:bg-[#334155]/50'
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Bottom bar — shows mode badge */}
        <div className={`px-5 py-3 border-t text-xs ${
          isLive
            ? 'border-red-500/20 text-red-400'
            : 'border-[#334155] text-[#64748b]'
        }`}>
          v1.0.0 · {isLive ? '🔴 Live Mode' : 'Paper Mode'}
        </div>
      </aside>

      {/* ── Main content ─────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top header bar */}
        <header
          className={`flex items-center justify-end gap-3 px-6 py-3 border-b transition-colors duration-300 ${
            isLive
              ? 'bg-red-500/[0.03] border-red-500/15'
              : 'bg-[#0f172a] border-[#1e293b]'
          }`}
        >
          <AlpacaStatusBadge status={accountStatus} />
          <TradingModeToggle
            mode={tradingMode}
            onSwitch={handleModeSwitch}
            loading={modeLoading}
          />
        </header>

        {/* Page content */}
        <main
          className={`flex-1 overflow-y-auto p-6 transition-colors duration-300 ${
            isLive ? 'bg-[#0f172a] ring-inset ring-1 ring-red-500/5' : 'bg-[#0f172a]'
          }`}
        >
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/trade-desk" element={<TradeDeskPage />} />
            <Route path="/performance" element={<PerformancePage />} />
          </Routes>
        </main>
      </div>

      {/* ── Live Trading Confirmation Modal ───────────────────────── */}
      <ConfirmLiveModal
        open={showLiveConfirm}
        onConfirm={() => doSwitch('live')}
        onCancel={() => setShowLiveConfirm(false)}
      />
    </div>
  )
}
