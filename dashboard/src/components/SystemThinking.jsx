import { useState } from 'react'
import { Brain, ChevronDown, ChevronRight } from 'lucide-react'

function relativeTime(isoString) {
  if (!isoString) return null
  const diff = Date.now() - new Date(isoString).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  return `${Math.floor(mins / 60)}h ago`
}

export default function SystemThinking({ reasoning }) {
  const [expanded, setExpanded] = useState(false)
  const latest = reasoning?.[0]
  const relTime = relativeTime(latest?.timestamp)

  return (
    <div className="border-l-2 border-purple-500/60 bg-purple-500/5 rounded-r-xl rounded-tl-xl p-4 border border-l-0 border-purple-500/20">
      <div
        className="flex items-start gap-3 cursor-pointer"
        onClick={() => latest && setExpanded(e => !e)}
      >
        <Brain size={16} className="text-purple-400 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-purple-300 uppercase tracking-wide">
              System Assessment
            </span>
            {relTime && (
              <span className="text-xs text-slate-500 shrink-0">{relTime}</span>
            )}
          </div>
          <p className="mt-1 text-sm text-slate-200 leading-snug">
            {latest?.summary || (
              <span className="text-slate-500 italic">
                AI reasoning not available — running in rule-based mode
              </span>
            )}
          </p>
        </div>
        {latest && (
          expanded
            ? <ChevronDown size={14} className="text-purple-400/60 shrink-0 mt-1" />
            : <ChevronRight size={14} className="text-purple-400/60 shrink-0 mt-1" />
        )}
      </div>
      {expanded && latest && (
        <pre className="mt-3 p-3 bg-[#0f172a] rounded-lg text-xs text-slate-400 whitespace-pre-wrap leading-relaxed overflow-auto max-h-96">
          {latest.reasoning}
        </pre>
      )}
    </div>
  )
}
