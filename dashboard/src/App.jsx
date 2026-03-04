import { useState, useEffect } from 'react'
import { Routes, Route, NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Briefcase,
  ScrollText,
  Bot,
  Search,
  FlaskConical,
} from 'lucide-react'
import Portfolio from './pages/Portfolio'
import Positions from './pages/Positions'
import TradeHistory from './pages/TradeHistory'
import AgentStatus from './pages/AgentStatus'
import ScannerWorkshop from './pages/ScannerWorkshop'
import Backtest from './pages/Backtest'
import TradingModeToggle from './components/TradingModeToggle'
import ConfirmLiveModal from './components/ConfirmLiveModal'
import { fetchTradingMode, updateTradingMode } from './api'

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Portfolio' },
  { to: '/positions', icon: Briefcase, label: 'Positions' },
  { to: '/trades', icon: ScrollText, label: 'Trades' },
  { to: '/agents', icon: Bot, label: 'Agents' },
  { to: '/scanner', icon: Search, label: 'Scanner' },
  { to: '/backtest', icon: FlaskConical, label: 'Backtest' },
]

export default function App() {
  const [tradingMode, setTradingMode] = useState('paper')
  const [modeLoading, setModeLoading] = useState(false)
  const [showLiveConfirm, setShowLiveConfirm] = useState(false)

  const isLive = tradingMode === 'live'

  // Fetch current trading mode on mount
  useEffect(() => {
    fetchTradingMode()
      .then((data) => setTradingMode(data.trading_mode))
      .catch(() => setTradingMode('paper'))
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
          className={`flex items-center justify-end px-6 py-3 border-b transition-colors duration-300 ${
            isLive
              ? 'bg-red-500/[0.03] border-red-500/15'
              : 'bg-[#0f172a] border-[#1e293b]'
          }`}
        >
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
            <Route path="/" element={<Portfolio />} />
            <Route path="/positions" element={<Positions />} />
            <Route path="/trades" element={<TradeHistory />} />
            <Route path="/agents" element={<AgentStatus />} />
            <Route path="/scanner" element={<ScannerWorkshop />} />
            <Route path="/backtest" element={<Backtest />} />
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
