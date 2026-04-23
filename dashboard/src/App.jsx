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
    <div className="w95" style={{ display: 'flex', height: '100vh' }}>
      {/* ── Sidebar ──────────────────────────────────────────── */}
      <aside style={{
        width: 180,
        flexShrink: 0,
        background: '#000080',
        display: 'flex',
        flexDirection: 'column',
        borderRight: '2px outset #dfdfdf',
      }}>
        <div style={{
          padding: '10px 12px 8px',
          borderBottom: '1px solid #0000b0',
        }}>
          <div style={{
            color: '#ffffff',
            fontFamily: 'var(--w95-font-ui)',
            fontWeight: 'bold',
            fontSize: 14,
          }}>
            Premium Trader
          </div>
          <div style={{
            color: '#a0a0ff',
            fontFamily: 'var(--w95-font-ui)',
            fontSize: 10,
            marginTop: 1,
          }}>
            Multi-Agent Options
          </div>
        </div>

        <nav style={{ flex: 1, padding: '6px 0' }}>
          {navItems.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              style={({ isActive }) => ({
                display: 'block',
                padding: '6px 12px',
                fontFamily: 'var(--w95-font-ui)',
                fontSize: 12,
                color: isActive ? '#ffffff' : '#c0c0ff',
                background: isActive ? '#0000b0' : 'transparent',
                fontWeight: isActive ? 'bold' : 'normal',
                textDecoration: 'none',
                borderLeft: isActive ? '3px solid #ffffff' : '3px solid transparent',
                cursor: 'pointer',
              })}
            >
              {label}
            </NavLink>
          ))}
        </nav>

        <div style={{
          padding: '8px 12px',
          borderTop: '1px solid #0000b0',
          color: '#8080c0',
          fontFamily: 'var(--w95-font-ui)',
          fontSize: 10,
        }}>
          v1.0 · Paper Mode
        </div>
      </aside>

      {/* ── Main content ─────────────────────────────────────── */}
      <main style={{
        flex: 1,
        overflow: 'auto',
        background: '#c0c0c0',
      }}>
        <Routes>
          <Route path="/" element={<ErrorBoundary><CommandCenterPage /></ErrorBoundary>} />
          <Route path="/history" element={<ErrorBoundary><HistoryPage /></ErrorBoundary>} />
          <Route path="/rules" element={<ErrorBoundary><RulesPage /></ErrorBoundary>} />
        </Routes>
      </main>
    </div>
  )
}
