import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { etClock, isAdmin, MONO } from '../lib/design'

const TABS = [
  { to: '/', label: 'Command Center' },
  { to: '/pipeline', label: 'Pipeline' },
  { to: '/trades', label: 'Trades & Learning' },
  { to: '/chat', label: 'Chat' },
]

/**
 * Navy top nav bar (admin variant: dark red on the Agents screen).
 * Active tab renders as a raised button; inactive tabs are flat.
 */
export default function NavBar() {
  const [clock, setClock] = useState(etClock())
  const location = useLocation()
  const admin = isAdmin()
  const onAgents = location.pathname.startsWith('/agents')

  useEffect(() => {
    const t = setInterval(() => setClock(etClock()), 15000)
    return () => clearInterval(t)
  }, [])

  const bg = onAgents ? '#400000' : '#000080'
  const inactiveColor = onAgents ? '#c0a0a0' : '#c0c0ff'

  const tabStyle = (isActive) =>
    isActive
      ? { border: '2px outset #dfdfdf', background: '#c0c0c0', padding: '2px 12px', fontSize: 11, fontWeight: 'bold', color: '#000', textDecoration: 'none' }
      : { padding: '2px 12px', fontSize: 11, color: inactiveColor, textDecoration: 'none' }

  return (
    <div style={{ background: bg, display: 'flex', alignItems: 'center', padding: '2px 4px', gap: 4, borderBottom: '2px outset #dfdfdf', fontFamily: 'Tahoma, sans-serif' }}>
      <span style={{ color: '#fff', fontWeight: 'bold', fontSize: 12, padding: '2px 8px 2px 4px' }}>PREMIUM TRADER</span>
      {TABS.map(({ to, label }) => (
        <NavLink key={to} to={to} end={to === '/'} style={({ isActive }) => tabStyle(isActive)}>
          {label}
        </NavLink>
      ))}
      {admin && (
        <NavLink
          to="/agents"
          style={({ isActive }) =>
            isActive
              ? { ...tabStyle(true), whiteSpace: 'nowrap' }
              : { padding: '2px 12px', fontSize: 11, color: '#6060a0', whiteSpace: 'nowrap', textDecoration: 'none' }
          }
        >
          Agents {'\u{1F512}'}
        </NavLink>
      )}
      <span style={{ flex: 1 }} />
      <span style={{ fontFamily: MONO, fontSize: 10, color: onAgents ? '#ff8080' : '#a0a0ff' }}>
        {onAgents ? `ADMIN SESSION · ${clock.split('·')[1]?.trim() || clock}` : clock}
      </span>
    </div>
  )
}
