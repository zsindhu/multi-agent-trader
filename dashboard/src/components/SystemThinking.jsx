import { useState } from 'react'
import { Brain, ChevronDown, AlertTriangle, Shield } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const mdComponents = {
  h1: ({children}) => <h1 className="text-base font-bold text-white mt-3 mb-1.5">{children}</h1>,
  h2: ({children}) => <h2 className="text-sm font-bold text-white mt-3 mb-1">{children}</h2>,
  h3: ({children}) => <h3 className="text-sm font-semibold text-slate-200 mt-2 mb-1">{children}</h3>,
  p: ({children}) => <p className="text-sm text-slate-300 mb-2 leading-relaxed">{children}</p>,
  strong: ({children}) => <strong className="text-white font-semibold">{children}</strong>,
  em: ({children}) => <em className="text-slate-300 italic">{children}</em>,
  ul: ({children}) => <ul className="list-disc list-inside space-y-0.5 text-sm text-slate-300 mb-2 pl-1">{children}</ul>,
  ol: ({children}) => <ol className="list-decimal list-inside space-y-0.5 text-sm text-slate-300 mb-2 pl-1">{children}</ol>,
  li: ({children}) => <li className="text-slate-300">{children}</li>,
  table: ({children}) => (
    <div className="overflow-x-auto my-2">
      <table className="w-full text-xs border-collapse">{children}</table>
    </div>
  ),
  thead: ({children}) => <thead className="bg-[#0a0f1e] border-b border-slate-700">{children}</thead>,
  tbody: ({children}) => <tbody>{children}</tbody>,
  tr: ({children}) => <tr className="border-b border-slate-800 hover:bg-slate-800/30">{children}</tr>,
  th: ({children}) => <th className="text-left text-slate-400 px-3 py-2 font-medium">{children}</th>,
  td: ({children}) => <td className="text-slate-300 px-3 py-2 whitespace-nowrap">{children}</td>,
  hr: () => <hr className="border-slate-700 my-3" />,
  blockquote: ({children}) => (
    <blockquote className="border-l-2 border-amber-500 pl-3 py-0.5 text-amber-200/80 bg-amber-500/5 rounded-r my-2">
      {children}
    </blockquote>
  ),
  code: ({children}) => <code className="bg-slate-900 text-emerald-400 px-1 py-0.5 rounded text-xs font-mono">{children}</code>,
  pre: ({children}) => <pre className="bg-slate-900/60 rounded p-2 my-2 overflow-auto text-xs">{children}</pre>,
}

function relativeTime(isoString) {
  if (!isoString) return null
  const diff = Date.now() - new Date(isoString).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  return `${Math.floor(mins / 60)}h ago`
}

function getAccent(text = '') {
  const t = text.toLowerCase()
  if (/crisis|danger|severe|emergency/.test(t)) return 'crisis'
  if (/risk.off|bearish|caution|conservative/.test(t)) return 'risk-off'
  if (/neutral|mixed|uncertain/.test(t)) return 'neutral'
  return 'default'
}

const ACCENT = {
  'crisis':   { border: 'border-red-500',      bg: 'bg-red-500/5',    Icon: AlertTriangle, iconColor: 'text-red-400' },
  'risk-off': { border: 'border-amber-500',     bg: 'bg-amber-500/5',  Icon: Shield,        iconColor: 'text-amber-400' },
  'neutral':  { border: 'border-blue-400',      bg: 'bg-blue-500/5',   Icon: Brain,         iconColor: 'text-blue-400' },
  'default':  { border: 'border-purple-500/60', bg: 'bg-purple-500/5', Icon: Brain,         iconColor: 'text-purple-400' },
}

export default function SystemThinking({ reasoning }) {
  const [expanded, setExpanded] = useState(false)
  const latest = reasoning?.[0]
  const relTime = relativeTime(latest?.timestamp)
  const { border, bg, Icon, iconColor } = ACCENT[getAccent(latest?.summary)]

  return (
    <div className={`bg-[#1e293b] rounded-xl border-l-4 ${border} ${bg} overflow-hidden`}>
      <div className="px-5 py-4">
        <div className="flex items-start justify-between mb-2">
          <div className="flex items-center gap-2">
            <Icon size={16} className={`${iconColor} shrink-0`} />
            <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">
              System Assessment
            </span>
          </div>
          {relTime && <span className="text-xs text-slate-500">{relTime}</span>}
        </div>
        <p className="text-sm text-slate-200 leading-snug font-medium">
          {latest?.summary || (
            <span className="text-slate-500 italic">
              AI reasoning not available — running in rule-based mode
            </span>
          )}
        </p>
      </div>

      {latest?.reasoning && (
        <button
          onClick={() => setExpanded(e => !e)}
          className="w-full flex items-center justify-between px-5 py-2.5 border-t border-[#334155]/50 hover:bg-[#334155]/20 transition-colors"
        >
          <span className="text-xs text-slate-400">
            {expanded ? 'Hide full analysis' : 'View full analysis'}
          </span>
          <ChevronDown
            size={14}
            className={`text-slate-500 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
          />
        </button>
      )}

      {expanded && latest && (
        <div className="px-5 pb-5 border-t border-[#334155]/50">
          <div className="mt-3 max-h-[500px] overflow-y-auto pr-1 custom-scrollbar">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
              {latest.reasoning}
            </ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  )
}
