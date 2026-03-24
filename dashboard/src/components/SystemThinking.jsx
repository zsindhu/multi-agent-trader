import { useState } from 'react'
import { Brain, ChevronDown, ChevronRight } from 'lucide-react'
import ReactMarkdown from 'react-markdown'

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
  table: ({children}) => <table className="w-full text-xs border-collapse my-2">{children}</table>,
  thead: ({children}) => <thead className="bg-slate-900/60">{children}</thead>,
  th: ({children}) => <th className="text-left text-slate-400 px-2 py-1 border-b border-slate-700 font-medium">{children}</th>,
  td: ({children}) => <td className="text-slate-300 px-2 py-1 border-b border-slate-800">{children}</td>,
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
        <div className="mt-3 p-3 bg-[#0f172a]/80 rounded-lg overflow-auto max-h-96 border border-purple-500/10">
          <ReactMarkdown components={mdComponents}>{latest.reasoning}</ReactMarkdown>
        </div>
      )}
    </div>
  )
}
