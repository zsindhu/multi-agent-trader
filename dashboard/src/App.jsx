import { Routes, Route, Navigate } from 'react-router-dom'
import CommandCenterPage from './pages/CommandCenterPage'
import PipelinePage from './pages/PipelinePage'
import TradesPage from './pages/TradesPage'
import AgentsPage from './pages/AgentsPage'
import ChatPage from './pages/ChatPage'
import RulesPage from './pages/RulesPage'
import NavBar from './components/NavBar'
import ErrorBoundary from './components/ErrorBoundary'
import { checkAdminParam, isAdmin, UI } from './lib/design'
import './win95.css'

checkAdminParam()

function AdminGate({ children }) {
  if (isAdmin()) return children
  return (
    <div style={{ padding: 40, fontFamily: UI, fontSize: 12, textAlign: 'center' }}>
      <div style={{ fontSize: 24 }}>{'\u{1F512}'}</div>
      <div style={{ fontWeight: 'bold', marginTop: 8 }}>Agents screen is admin-only.</div>
      <div style={{ color: '#808080', marginTop: 4 }}>Append ?admin=1 to the URL to unlock this session.</div>
    </div>
  )
}

export default function App() {
  return (
    <div className="w95" style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#c0c0c0' }}>
      <NavBar />
      <main style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
        <Routes>
          <Route path="/" element={<ErrorBoundary><CommandCenterPage /></ErrorBoundary>} />
          <Route path="/pipeline" element={<ErrorBoundary><PipelinePage /></ErrorBoundary>} />
          <Route path="/trades" element={<ErrorBoundary><TradesPage /></ErrorBoundary>} />
          <Route path="/history" element={<Navigate to="/trades" replace />} />
          <Route path="/agents" element={<ErrorBoundary><AdminGate><AgentsPage /></AdminGate></ErrorBoundary>} />
          <Route path="/chat" element={<ErrorBoundary><ChatPage /></ErrorBoundary>} />
          {/* Legacy reference page — reachable by URL, not in nav */}
          <Route path="/rules" element={<ErrorBoundary><RulesPage /></ErrorBoundary>} />
        </Routes>
      </main>
    </div>
  )
}
