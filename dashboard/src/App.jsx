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

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Portfolio' },
  { to: '/positions', icon: Briefcase, label: 'Positions' },
  { to: '/trades', icon: ScrollText, label: 'Trades' },
  { to: '/agents', icon: Bot, label: 'Agents' },
  { to: '/scanner', icon: Search, label: 'Scanner' },
  { to: '/backtest', icon: FlaskConical, label: 'Backtest' },
]

export default function App() {
  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <aside className="w-56 flex-shrink-0 bg-[#1e293b] border-r border-[#334155] flex flex-col">
        <div className="px-5 py-5 border-b border-[#334155]">
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
                    ? 'bg-[#334155] text-white font-medium border-r-2 border-blue-500'
                    : 'text-[#94a3b8] hover:text-white hover:bg-[#334155]/50'
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="px-5 py-3 border-t border-[#334155] text-xs text-[#64748b]">
          v1.0.0 · Paper Mode
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto bg-[#0f172a] p-6">
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
  )
}
