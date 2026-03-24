import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

function relativeTime(isoString) {
  if (!isoString) return ''
  const diff = Date.now() - new Date(isoString).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return new Date(isoString).toLocaleDateString()
}

function entryBorderColor(log) {
  const agent = log.agent_name || ''
  const action = (log.action || '').toLowerCase()
  if (agent === 'Lead-Agent') return 'border-l-purple-500/70'
  if (action.includes('alert') || action.includes('risk')) return 'border-l-red-500 border-l-2'
  if (action.includes('close') || action.includes('buy_to_close')) return 'border-l-red-400/70'
  if (action.includes('sell_to_open') || action.includes('buy_to_open')) return 'border-l-emerald-500/70'
  if (action.includes('regime')) return 'border-l-amber-500/70'
  return 'border-l-slate-600/50'
}

function agentBadgeColor(agentName) {
  const colors = {
    'Lead-Agent': 'bg-purple-500/20 text-purple-300',
    'Covered-Calls': 'bg-indigo-500/20 text-indigo-300',
    'Cash-Secured-Puts': 'bg-emerald-500/20 text-emerald-300',
    'Wheel': 'bg-pink-500/20 text-pink-300',
    'Scanner': 'bg-amber-500/20 text-amber-300',
  }
  return colors[agentName] || 'bg-slate-500/20 text-slate-400'
}

function EntryRow({ log }) {
  const [open, setOpen] = useState(false)
  const border = entryBorderColor(log)
  const badge = agentBadgeColor(log.agent_name)

  return (
    <div
      className={`border-l pl-3 py-1.5 cursor-pointer group ${border}`}
      onClick={() => log.rationale && setOpen(o => !o)}
    >
      <div className="flex items-start gap-2">
        <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded shrink-0 mt-0.5 ${badge}`}>
          {log.agent_name || '—'}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-slate-300 leading-snug truncate">
              {log.order_status || log.action || '—'}
            </p>
            <span className="text-[10px] text-slate-600 shrink-0">{relativeTime(log.created_at)}</span>
          </div>
        </div>
        {log.rationale && (
          open
            ? <ChevronDown size={12} className="text-slate-600 shrink-0 mt-0.5" />
            : <ChevronRight size={12} className="text-slate-600 shrink-0 mt-0.5 opacity-0 group-hover:opacity-100" />
        )}
      </div>
      {open && log.rationale && (
        <p className="mt-1.5 text-xs text-slate-500 leading-relaxed pl-0.5">
          {log.rationale}
        </p>
      )}
    </div>
  )
}

export default function ActivityFeed({ entries = [], limit = 10 }) {
  const visible = entries.slice(0, limit)

  if (visible.length === 0) {
    return (
      <p className="text-xs text-slate-600 italic py-2">No activity yet.</p>
    )
  }

  return (
    <div className="space-y-1">
      {visible.map((log) => (
        <EntryRow key={log.id} log={log} />
      ))}
    </div>
  )
}
