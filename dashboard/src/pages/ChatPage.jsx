/**
 * Chat — design 3d. Tool-call transparency with per-exchange latency,
 * data-source list, and suggested queries. Keeps the original page's
 * session + fetch mechanics (/api/chat, session_id in localStorage).
 */
import { useState, useRef, useEffect } from 'react'
import Panel from '../components/Panel'
import { BarMeter } from '../components/bits'
import { MONO, UI } from '../lib/design'

const API_BASE = '/api'
const OLIVE = '#808000'
const GREEN = '#008000'

function formatTimestamp() {
  return new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
}

/** Lightweight markdown → HTML for agent responses. Handles bold, code blocks, inline code, headers, and lists. */
function renderMarkdown(text) {
  if (!text) return ''
  let html = text
    // Escape HTML
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    // Code blocks (``` ... ```)
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre style="background:#e0e0e0;padding:4px 6px;border:1px solid #c0c0c0;overflow-x:auto;margin:4px 0;font-size:11px">$2</pre>')
    // Inline code
    .replace(/`([^`]+)`/g, '<code style="background:#e0e0e0;padding:1px 3px;font-size:11px">$1</code>')
    // Bold
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // Italic
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Headers (### → h4, ## → h3, # → h2)
    .replace(/^### (.+)$/gm, '<strong style="font-size:12px">$1</strong>')
    .replace(/^## (.+)$/gm, '<strong style="font-size:13px">$1</strong>')
    .replace(/^# (.+)$/gm, '<strong style="font-size:14px">$1</strong>')
    // Bullet lists
    .replace(/^[-*] (.+)$/gm, '&nbsp;&nbsp;• $1')
    // Numbered lists
    .replace(/^(\d+)\. (.+)$/gm, '&nbsp;&nbsp;$1. $2')
    // Line breaks
    .replace(/\n/g, '<br/>')
  return html
}

function MarkdownContent({ text }) {
  return <span dangerouslySetInnerHTML={{ __html: renderMarkdown(text) }} />
}

/** actions_taken entries may be strings or dicts ({type, query, ...}) — describe defensively. */
function describeAction(a) {
  let s
  if (typeof a === 'string') {
    s = a
  } else if (a && typeof a === 'object') {
    const inner = a.action && typeof a.action === 'object' ? a.action : a
    const type = inner.type || 'action'
    if (type === 'sql') s = `sql_query — ${inner.query || ''}`
    else if (type === 'semantic') s = `semantic_search — ${inner.query || ''}`
    else if (type === 'write_playbook') s = `write_playbook — ${inner.category || ''}: ${inner.content || ''}`
    else if (type === 'deactivate_playbook') s = `deactivate_playbook — entry ${inner.entry_id ?? '?'}`
    else s = `${type} — ${JSON.stringify(inner)}`
  } else {
    s = String(a)
  }
  s = s.replace(/\s+/g, ' ').trim()
  return s.length > 80 ? s.slice(0, 80) + '…' : s
}

function truncateLabel(q, n = 14) {
  const s = (q || '').replace(/\s+/g, ' ').trim()
  return s.length > n ? s.slice(0, n) + '…' : s
}

const SUGGESTED = [
  'Win rate by sleeve this month',
  "Which signals fired on yesterday's promotions?",
  'Show unfilled entry orders this week',
  'Biggest P&L drift trades vs Alpaca',
]

const CAN_SEE = [
  '✓ trades & outcomes',
  '✓ name_observations (sweep-aware)',
  '✓ cycle_snapshots & envelopes',
  '✓ playbook',
]

// ── Message rendering ────────────────────────────────────────

function UserBubble({ msg }) {
  return (
    <div style={{ maxWidth: '70%', alignSelf: 'flex-end', border: '1px solid #808080', background: '#e8e8ff', padding: '4px 8px' }}>
      <div style={{ fontSize: 9, color: '#808080', fontFamily: UI, textAlign: 'right' }}>YOU · {msg.time}</div>
      <span style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</span>
    </div>
  )
}

function AgentBubble({ msg }) {
  const actions = Array.isArray(msg.actions) ? msg.actions : []
  const secs = msg.elapsedMs != null ? (msg.elapsedMs / 1000).toFixed(1) : null
  return (
    <div style={{ maxWidth: '85%', alignSelf: 'flex-start' }}>
      {actions.length > 0 && (
        <div style={{ border: '1px solid #c0c0c0', background: '#f0f0f0', padding: '3px 6px', fontFamily: MONO, fontSize: 10, color: '#404040', marginBottom: 2 }}>
          {actions.map((a, i) => (
            <div key={i} style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {'▶'} {describeAction(a)}
            </div>
          ))}
          {msg.elapsedMs != null && (
            <div>
              {'▶'} total{' '}
              <span style={{ color: msg.elapsedMs < 3000 ? GREEN : OLIVE }}>
                {msg.elapsedMs.toLocaleString('en-US')}ms
              </span>
            </div>
          )}
        </div>
      )}
      <div style={{ border: '1px solid #808080', background: msg.isError ? '#ffe8e8' : '#fff', padding: '4px 8px', wordBreak: 'break-word' }}>
        <div style={{ fontSize: 9, color: '#808080', fontFamily: UI }}>
          AGENT · {msg.time}{secs != null ? ` · ${secs}s` : ''}
        </div>
        <MarkdownContent text={msg.content} />
      </div>
    </div>
  )
}

// ── Right rail panels ────────────────────────────────────────

function LatencyPanel({ latencies }) {
  if (latencies.length === 0) {
    return (
      <Panel title="Latency (this session)">
        <div style={{ fontFamily: UI, fontSize: 10, color: '#808080' }}>
          No queries yet this session — send a message to see real response times.
        </div>
      </Panel>
    )
  }
  const maxMs = Math.max(...latencies.map(l => l.ms), 1)
  const sorted = [...latencies].map(l => l.ms).sort((a, b) => a - b)
  const p50 = sorted[Math.floor((sorted.length - 1) / 2)]
  return (
    <Panel title="Latency (this session)">
      <div style={{ fontFamily: MONO, fontSize: 11 }}>
        {latencies.map((l, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '1px 0' }}>
            <span style={{ width: 92, textAlign: 'right', fontFamily: UI, fontSize: 10, flexShrink: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={l.q}>
              {truncateLabel(l.q)}
            </span>
            <BarMeter pct={(l.ms / maxMs) * 100} color={l.ms < 3000 ? '#000080' : OLIVE} height={10} />
            <span style={{ width: 58, textAlign: 'right', flexShrink: 0 }}>{l.ms.toLocaleString('en-US')}ms</span>
          </div>
        ))}
        <div style={{ fontFamily: UI, fontSize: 10, color: '#808080', marginTop: 4, borderTop: '1px solid #808080', paddingTop: 3 }}>
          p50 {(p50 / 1000).toFixed(1)}s over {latencies.length} {latencies.length === 1 ? 'query' : 'queries'}
        </div>
      </div>
    </Panel>
  )
}

function CanSeePanel() {
  return (
    <Panel title="Agent Can See">
      <div style={{ fontFamily: MONO, fontSize: 10, lineHeight: 1.7 }}>
        {CAN_SEE.map(l => <div key={l}>{l}</div>)}
        <div style={{ color: '#808080' }}>{'×'} cannot place or modify orders</div>
      </div>
    </Panel>
  )
}

function SuggestedPanel({ onPick }) {
  return (
    <Panel title="Suggested Queries" style={{ flex: 1, minHeight: 0 }} bodyStyle={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      {SUGGESTED.map(q => (
        <button
          key={q}
          onClick={() => onPick(q)}
          style={{
            border: '2px outset #dfdfdf', background: '#c0c0c0', padding: '3px 8px',
            fontSize: 10, fontFamily: UI, textAlign: 'left', cursor: 'pointer',
          }}
        >
          {q}
        </button>
      ))}
    </Panel>
  )
}

// ── Page ─────────────────────────────────────────────────────

export default function ChatPage() {
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Premium Trader Chat Agent ready. Ask me anything about trades, strategy, performance, or system data.', time: formatTimestamp() },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState(() => localStorage.getItem('chat_session_id') || null)
  const [latencies, setLatencies] = useState([]) // [{q, ms}] — this session's real exchanges
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    if (sessionId) localStorage.setItem('chat_session_id', sessionId)
  }, [sessionId])

  const sendMessage = async () => {
    const text = input.trim()
    if (!text || loading) return

    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: text, time: formatTimestamp() }])
    setLoading(true)

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || res.statusText)
      }

      const data = await res.json()
      setSessionId(data.session_id)
      if (data.elapsed_ms != null) {
        setLatencies(prev => [...prev, { q: text, ms: data.elapsed_ms }])
      }
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.response,
        data: data.data,
        actions: data.actions_taken,
        elapsedMs: data.elapsed_ms,
        time: formatTimestamp(),
      }])
    } catch (err) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `Error: ${err.message}`,
        time: formatTimestamp(),
        isError: true,
      }])
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  const clearSession = () => {
    if (sessionId) {
      fetch(`${API_BASE}/chat/session/${sessionId}`, { method: 'DELETE' }).catch(() => {})
    }
    setMessages([
      { role: 'assistant', content: 'Session cleared. Ask me anything.', time: formatTimestamp() },
    ])
    setLatencies([])
    const newId = crypto.randomUUID()
    setSessionId(newId)
    localStorage.setItem('chat_session_id', newId)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const pickSuggested = (q) => {
    setInput(q)
    inputRef.current?.focus()
  }

  const shortId = sessionId ? sessionId.slice(0, 4) : 'new'
  const avgMs = latencies.length
    ? latencies.reduce((s, l) => s + l.ms, 0) / latencies.length
    : null

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: '1fr 330px', gap: 4, padding: 4 }}>
      {/* chat window — Panel chrome built manually so the input row sits outside the inset body */}
      <div style={{ border: '2px outset #dfdfdf', background: '#c0c0c0', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={{ background: '#000080', color: '#fff', fontSize: 12, fontWeight: 'bold', padding: '2px 4px', display: 'flex', alignItems: 'center', fontFamily: UI }}>
          <span style={{ flex: 1 }}>{'\u{1F4AC}'} Chat Agent — session #{shortId}</span>
          {avgMs != null && (
            <span style={{ fontWeight: 'normal', fontSize: 10, color: '#80ff80', fontFamily: MONO }}>
              AVG RESPONSE {(avgMs / 1000).toFixed(1)}s
            </span>
          )}
        </div>
        <div style={{
          border: '2px inset #dfdfdf', margin: 2, background: '#fff', overflowY: 'auto', flex: 1, minHeight: 0,
          padding: 8, fontSize: 11, fontFamily: UI, display: 'flex', flexDirection: 'column', gap: 8,
        }}>
          {messages.map((msg, i) => (
            msg.role === 'user' ? <UserBubble key={i} msg={msg} /> : <AgentBubble key={i} msg={msg} />
          ))}
          {loading && (
            <div style={{ maxWidth: '85%', alignSelf: 'flex-start', border: '1px solid #808080', background: '#fff', padding: '4px 8px' }}>
              <div style={{ fontSize: 9, color: '#808080', fontFamily: UI }}>AGENT · {formatTimestamp()}</div>
              <span style={{ color: '#808080' }}>...</span>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
        <div style={{ display: 'flex', gap: 4, padding: 4, background: '#d4d0c8', borderTop: '1px solid #808080' }}>
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about trades, sleeves, agents, data..."
            disabled={loading}
            style={{
              flex: 1, border: '2px inset #dfdfdf', background: '#fff', padding: '4px 6px',
              fontFamily: MONO, fontSize: 11, outline: 'none',
            }}
          />
          <button
            onClick={sendMessage}
            disabled={loading || !input.trim()}
            style={{
              border: '2px outset #dfdfdf', background: '#c0c0c0', padding: '4px 16px',
              fontSize: 11, fontWeight: 'bold', fontFamily: UI,
              cursor: loading || !input.trim() ? 'default' : 'pointer',
              color: loading ? '#808080' : '#000',
            }}
          >
            {loading ? 'Wait...' : 'Send'}
          </button>
          <button
            onClick={clearSession}
            disabled={loading}
            title="Clear this session's history"
            style={{
              border: '2px outset #dfdfdf', background: '#c0c0c0', padding: '4px 8px',
              fontSize: 11, fontFamily: UI, cursor: loading ? 'default' : 'pointer',
            }}
          >
            New
          </button>
        </div>
      </div>

      {/* right rail */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minHeight: 0 }}>
        <LatencyPanel latencies={latencies} />
        <CanSeePanel />
        <SuggestedPanel onPick={pickSuggested} />
      </div>
    </div>
  )
}
