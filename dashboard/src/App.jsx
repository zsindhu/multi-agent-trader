import { Routes, Route, NavLink } from 'react-router-dom'
import CommandCenterPage from './pages/CommandCenterPage'
import HistoryPage from './pages/HistoryPage'
import RulesPage from './pages/RulesPage'
import ErrorBoundary from './components/ErrorBoundary'
import './win95.css'

const navItems = [
  { to: '/', label: 'Command Center' },
  { to: '/history', label: 'History' },
  { to: '/rules', label: 'Rules & Logic' },
]

export default function App() {
  return (
    <div className="w95 w95-app">
      {/* ── Mobile top bar (hidden on desktop) ───────────────── */}
      <nav className="w95-topbar">
        <span className="w95-topbar-title">Premium Trader</span>
        {navItems.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) => `w95-topbar-link ${isActive ? 'active' : ''}`}
          >
            {label}
          </NavLink>
        ))}
      </nav>

      {/* ── Sidebar (hidden on mobile) ───────────────────────── */}
      <aside className="w95-sidebar">
        <div className="w95-sidebar-header">
          <div className="w95-sidebar-title">Premium Trader</div>
          <div className="w95-sidebar-subtitle">Multi-Agent Options</div>
        </div>

        <nav className="w95-sidebar-nav">
          {navItems.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) => `w95-sidebar-link ${isActive ? 'active' : ''}`}
            >
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="w95-sidebar-footer">
          v1.0 · Paper Mode
        </div>
      </aside>

      {/* ── Main content ─────────────────────────────────────── */}
      <main className="w95-main">
        <Routes>
          <Route path="/" element={<ErrorBoundary><CommandCenterPage /></ErrorBoundary>} />
          <Route path="/history" element={<ErrorBoundary><HistoryPage /></ErrorBoundary>} />
          <Route path="/rules" element={<ErrorBoundary><RulesPage /></ErrorBoundary>} />
        </Routes>
      </main>
    </div>
  )
}
