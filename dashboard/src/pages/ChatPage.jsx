import { useState, useRef, useEffect } from 'react'
import W95Window from '../components/W95Window'

const API_BASE = '/api'

function formatTimestamp() {
  return new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
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

export default function ChatPage() {
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Premium Trader Chat Agent ready. Ask me anything about trades, strategy, performance, or system data.', time: formatTimestamp() }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState(() => localStorage.getItem('chat_session_id') || null)
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
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.response,
        data: data.data,
        actions: data.actions_taken,
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
      { role: 'assistant', content: 'Session cleared. Ask me anything.', time: formatTimestamp() }
    ])
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 60px)', padding: '8px', gap: '8px' }}>
      <W95Window title="Chat Agent" icon="C:\>">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
          <span style={{ fontSize: 11, color: '#808080' }}>
            Query trades, strategy, performance, and system data in natural language
          </span>
          <button
            className="w95-btn"
            style={{ fontSize: 11, padding: '2px 8px' }}
            onClick={clearSession}
          >
            New Session
          </button>
        </div>
      </W95Window>

      {/* Messages area */}
      <div style={{
        flex: 1,
        border: '2px inset #fff',
        backgroundColor: '#fff',
        overflowY: 'auto',
        padding: 8,
        fontFamily: '"Fixedsys", "Courier New", monospace',
        fontSize: 12,
        lineHeight: 1.5,
      }}>
        {messages.map((msg, i) => (
          <div key={i} style={{ marginBottom: 12 }}>
            <div style={{
              fontSize: 10,
              color: '#808080',
              marginBottom: 2,
            }}>
              {msg.role === 'user' ? 'You' : 'Agent'} · {msg.time}
            </div>
            <div style={{
              padding: '4px 8px',
              backgroundColor: msg.role === 'user' ? '#e8e8ff' : msg.isError ? '#ffe8e8' : '#f0f0f0',
              border: '1px solid #c0c0c0',
              wordBreak: 'break-word',
            }}>
              {msg.role === 'user' ? (
                <span style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</span>
              ) : (
                <MarkdownContent text={msg.content} />
              )}
            </div>
            {msg.actions && msg.actions.length > 0 && (
              <div style={{ fontSize: 10, color: '#808080', marginTop: 2 }}>
                Actions: {msg.actions.map(a => a.type).join(', ')}
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 10, color: '#808080', marginBottom: 2 }}>Agent · {formatTimestamp()}</div>
            <div style={{
              padding: '4px 8px',
              backgroundColor: '#f0f0f0',
              border: '1px solid #c0c0c0',
              color: '#808080',
              fontStyle: 'italic',
            }}>
              Thinking...
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div style={{ display: 'flex', gap: 4 }}>
        <textarea
          ref={inputRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about trades, strategy, performance..."
          disabled={loading}
          rows={2}
          style={{
            flex: 1,
            fontFamily: '"Fixedsys", "Courier New", monospace',
            fontSize: 12,
            padding: 4,
            border: '2px inset #fff',
            resize: 'none',
          }}
        />
        <button
          className="w95-btn"
          onClick={sendMessage}
          disabled={loading || !input.trim()}
          style={{ width: 80, alignSelf: 'stretch' }}
        >
          {loading ? 'Wait...' : 'Send'}
        </button>
      </div>
    </div>
  )
}
