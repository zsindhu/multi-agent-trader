import { CheckCircle2, XCircle, Clock, MinusCircle } from 'lucide-react'
import Badge from './Badge'

const AGENT_BADGE = {
  'Covered-Calls': 'indigo',
  'Cash-Secured-Puts': 'green',
  'Wheel': 'pink',
  'Lead-Agent': 'blue',
}

const AGENT_LABEL = {
  'Covered-Calls': 'CC',
  'Cash-Secured-Puts': 'CSP',
  'Wheel': 'Wheel',
  'Lead-Agent': 'Lead',
}

const ACTION_VERB = {
  close: 'Close',
  open_csp: 'Open CSP',
  open_cc: 'Open CC',
  open_wheel: 'Open Wheel',
  roll: 'Roll',
  hold: 'Hold',
  pause_worker: 'Pause',
  resume_worker: 'Resume',
  no_action: 'No action',
}

function StatusIcon({ status }) {
  if (status === 'filled') return <CheckCircle2 size={14} className="text-emerald-400" />
  if (status === 'rejected' || status === 'canceled') return <XCircle size={14} className="text-red-400" />
  if (status === 'submitted') return <Clock size={14} className="text-amber-400" />
  return <MinusCircle size={14} className="text-slate-500" />
}

/**
 * LastCycleActions — shows the most recent batch of LLM decisions with their execution status.
 * Filters to actions from the latest cycle (all entries within 2 minutes of the most recent).
 */
export default function LastCycleActions({ execLogs = [] }) {
  // Filter out the cycle_decision meta-entries; show actual trade actions
  const actions = execLogs.filter(l => l.action !== 'cycle_decision')

  if (actions.length === 0) return null

  // Group by the latest cycle: entries within 2 min of the most recent
  const latest = new Date(actions[0].created_at).getTime()
  const cycleActions = actions.filter(l => {
    const t = new Date(l.created_at).getTime()
    return latest - t < 120_000 // 2 minutes
  })

  if (cycleActions.length === 0) return null

  const ts = cycleActions[0].created_at
    ? new Date(cycleActions[0].created_at).toLocaleString('en-US', {
        month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
      })
    : ''

  return (
    <div className="bg-[#1e293b] rounded-xl border border-[#334155] overflow-hidden">
      <div className="px-5 py-3 flex items-center justify-between border-b border-[#334155]/50">
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
          Last Cycle Actions
        </h3>
        <span className="text-xs text-slate-500">{ts}</span>
      </div>
      <div className="px-5 py-3 space-y-2">
        {cycleActions.map(log => {
          const verb = ACTION_VERB[log.action] || log.action
          const badge = AGENT_BADGE[log.agent_name] || 'gray'
          const label = AGENT_LABEL[log.agent_name] || log.agent_name
          const type = log.contract_type === 'put' ? 'P' : log.contract_type === 'call' ? 'C' : ''
          const strike = log.strike ? `$${log.strike.toFixed(0)}` : ''

          return (
            <div
              key={log.id}
              className="flex items-center gap-3 py-1.5 text-sm"
            >
              <StatusIcon status={log.order_status} />
              <Badge variant={badge}>{label}</Badge>
              <span className="text-white font-medium">{verb}</span>
              <span className="text-slate-400">
                {log.symbol} {strike}{type}
              </span>
              <div className="flex-1" />
              <span className={`text-xs ${
                log.order_status === 'filled' ? 'text-emerald-400' :
                log.order_status === 'rejected' ? 'text-red-400' :
                log.order_status === 'submitted' ? 'text-amber-400' :
                'text-slate-500'
              }`}>
                {log.order_status || 'pending'}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
