import { useState, useRef, useEffect } from 'react'
import W95Window from '../components/W95Window'

const API_BASE = '/api'

function formatTimestamp() {
  return new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
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
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}>
              {msg.content}
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
