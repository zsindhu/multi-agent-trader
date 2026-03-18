import { useState } from 'react'
import clsx from 'clsx'
import Badge from './Badge'
import Spinner from './Spinner'
import { approveProposal, rejectProposal, modifyProposal, resetProposal } from '../api'

const AGENT_COLORS = {
  'Covered-Calls': '#6366f1',
  'Cash-Secured-Puts': '#10b981',
  'Wheel': '#ec4899',
}

const AGENT_BADGE_VARIANTS = {
  'Covered-Calls': 'indigo',
  'Cash-Secured-Puts': 'green',
  'Wheel': 'pink',
}

function fmt$(n) {
  if (n == null) return '—'
  return '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function fmtPct(n) {
  if (n == null) return '—'
  return Number(n).toFixed(1) + '%'
}

export default function ProposalCard({ proposal, onUpdate, remainingBuyingPower }) {
  const [loading, setLoading] = useState(null) // 'approve' | 'reject' | 'modify'
  const [modifyOpen, setModifyOpen] = useState(false)
  const [modifyDelta, setModifyDelta] = useState(Math.abs(proposal.delta).toFixed(2))
  const [modifyContracts, setModifyContracts] = useState(proposal.contracts)

  const accentColor = AGENT_COLORS[proposal.agent_name] || '#64748b'

  async function handleApprove() {
    setLoading('approve')
    try {
      const updated = await approveProposal(proposal.id)
      onUpdate?.(updated)
    } catch (e) {
      alert('Approval failed: ' + e.message)
    } finally {
      setLoading(null)
    }
  }

  async function handleReject() {
    setLoading('reject')
    try {
      const updated = await rejectProposal(proposal.id)
      onUpdate?.(updated)
    } catch (e) {
      alert('Rejection failed: ' + e.message)
    } finally {
      setLoading(null)
    }
  }

  async function handleReset() {
    setLoading('reset')
    try {
      const updated = await resetProposal(proposal.id)
      onUpdate?.(updated)
    } catch (e) {
      alert('Reset failed: ' + e.message)
    } finally {
      setLoading(null)
    }
  }

  async function handleModify() {
    setLoading('modify')
    try {
      const updated = await modifyProposal(proposal.id, {
        delta: parseFloat(modifyDelta),
        contracts: parseInt(modifyContracts),
      })
      onUpdate?.(updated)
      setModifyOpen(false)
    } catch (e) {
      alert('Modification failed: ' + e.message)
    } finally {
      setLoading(null)
    }
  }

  const expirationLabel = proposal.expiration
    ? new Date(proposal.expiration + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    : '—'

  const isExecuted = proposal.status === 'executed'
  const isRejected = proposal.status === 'rejected'
  const isDone = isExecuted || isRejected

  // Insufficient buying power: collateral exceeds what's remaining after prior approvals
  const collateral = proposal.collateral_required || 0
  const insufficientBP = (
    !isDone &&
    remainingBuyingPower != null &&
    remainingBuyingPower > 0 &&
    collateral > remainingBuyingPower
  )

  return (
    <div
      className={clsx(
        'bg-[#111827] rounded-xl border border-[#1e293b] overflow-hidden transition-opacity',
        isDone && 'opacity-60',
        insufficientBP && !isDone && 'opacity-50'
      )}
      style={{ borderLeft: `4px solid ${accentColor}` }}
    >
      {/* Top Row — Symbol + Agent + Rationale */}
      <div className="px-5 pt-4 pb-3 border-b border-[#1e293b]">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-xl font-bold text-white font-mono">{proposal.symbol}</span>
            <Badge variant={AGENT_BADGE_VARIANTS[proposal.agent_name] || 'gray'}>
              {proposal.agent_name}
            </Badge>
            <Badge variant={proposal.contract_type === 'call' ? 'indigo' : 'green'}>
              {proposal.contract_type.toUpperCase()}
            </Badge>
            {isExecuted && <Badge variant="blue">Executed</Badge>}
            {isRejected && <Badge variant="gray">Rejected</Badge>}
            {insufficientBP && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/20">
                Insufficient buying power
              </span>
            )}
          </div>
          <span className="text-xs text-[#64748b] flex-shrink-0">
            {proposal.asset_type?.toUpperCase()}
          </span>
        </div>
        <p className="text-xs text-[#94a3b8] mt-1.5 leading-relaxed">{proposal.rationale}</p>
      </div>

      {/* Contract + Financials + Risk */}
      <div className="px-5 py-3 space-y-2.5">
        {/* Contract row */}
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
          <DataPoint label="Strike" value={fmt$(proposal.strike)} />
          <DataPoint label="Exp" value={expirationLabel} />
          <DataPoint label="DTE" value={proposal.dte + 'd'} />
          <DataPoint label="Delta" value={'Δ' + Math.abs(proposal.delta).toFixed(2)} />
          <DataPoint label="OTM" value={fmtPct(proposal.distance_otm_pct)} />
        </div>

        {/* Financial row */}
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
          <DataPoint label="Premium" value={fmt$(proposal.premium_per_contract) + '/contract'} highlight />
          <DataPoint label="Total" value={fmt$(proposal.total_premium)} highlight />
          <DataPoint
            label="Collateral"
            value={
              proposal.pct_of_buying_power != null
                ? `${fmt$(proposal.collateral_required)} (${proposal.pct_of_buying_power.toFixed(1)}% BP)`
                : fmt$(proposal.collateral_required)
            }
            danger={insufficientBP}
          />
          <DataPoint label="Ann. Return" value={fmtPct(proposal.annualized_return)} highlight />
          <DataPoint label="PoP" value={fmtPct(proposal.probability_of_profit)} />
        </div>

        {/* Risk row */}
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
          <DataPoint label="Max Risk" value={fmt$(proposal.max_risk)} danger />
          <DataPoint label="IV Rank" value={proposal.iv_rank?.toFixed(0)} />
          {proposal.scanner_score != null && (
            <DataPoint label="Score" value={proposal.scanner_score.toFixed(3)} />
          )}
          {proposal.contracts > 1 && (
            <DataPoint label="Contracts" value={proposal.contracts} />
          )}
        </div>
      </div>

      {/* Modify inline editor */}
      {modifyOpen && !isDone && (
        <div className="px-5 pb-3 pt-1 border-t border-[#1e293b] bg-[#0a0f1e]">
          <p className="text-xs text-[#64748b] mb-2">Adjust parameters:</p>
          <div className="flex flex-wrap items-end gap-4">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-[#94a3b8]">Target Delta</span>
              <input
                type="number"
                min="0.05"
                max="0.50"
                step="0.05"
                value={modifyDelta}
                onChange={e => setModifyDelta(e.target.value)}
                className="w-24 bg-[#1e293b] border border-[#334155] rounded px-2 py-1 text-sm text-white"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-[#94a3b8]">Contracts</span>
              <input
                type="number"
                min="1"
                max="10"
                step="1"
                value={modifyContracts}
                onChange={e => setModifyContracts(e.target.value)}
                className="w-20 bg-[#1e293b] border border-[#334155] rounded px-2 py-1 text-sm text-white"
              />
            </label>
            <button
              onClick={handleModify}
              disabled={loading === 'modify'}
              className="px-3 py-1.5 text-sm rounded bg-amber-500/20 text-amber-400 border border-amber-500/30 hover:bg-amber-500/30 transition-colors disabled:opacity-50"
            >
              {loading === 'modify' ? <Spinner size="sm" /> : 'Recalculate'}
            </button>
            <button
              onClick={() => setModifyOpen(false)}
              className="px-3 py-1.5 text-sm rounded text-[#64748b] hover:text-[#94a3b8] transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Retry Row — for executed proposals that may have silently failed */}
      {isExecuted && (
        <div className="px-5 py-2.5 border-t border-[#1e293b] flex items-center gap-2">
          <span className="text-xs text-[#64748b]">Order not in Alpaca?</span>
          <button
            onClick={handleReset}
            disabled={!!loading}
            className="px-3 py-1 text-xs rounded border border-amber-500/30 text-amber-400 hover:bg-amber-500/10 transition-colors disabled:opacity-50"
          >
            {loading === 'reset' ? <Spinner size="sm" /> : 'Reset to Pending'}
          </button>
        </div>
      )}

      {/* Action Row */}
      {!isDone && (
        <div className="px-5 py-3 border-t border-[#1e293b] flex items-center gap-2">
          <button
            onClick={() => setModifyOpen(v => !v)}
            disabled={!!loading}
            className="px-3 py-1.5 text-sm rounded border border-[#334155] text-[#94a3b8] hover:border-[#64748b] hover:text-white transition-colors disabled:opacity-50"
          >
            Modify
          </button>
          <button
            onClick={handleReject}
            disabled={!!loading}
            className="px-3 py-1.5 text-sm rounded border border-red-500/30 text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-50"
          >
            {loading === 'reject' ? <Spinner size="sm" /> : 'Reject'}
          </button>
          <button
            onClick={handleApprove}
            disabled={!!loading}
            className="px-4 py-1.5 text-sm rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/30 transition-colors disabled:opacity-50 font-medium ml-auto"
          >
            {loading === 'approve' ? <Spinner size="sm" /> : 'Approve'}
          </button>
        </div>
      )}
    </div>
  )
}

function DataPoint({ label, value, highlight, danger }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wider text-[#64748b]">{label}</span>
      <span className={clsx(
        'text-sm font-mono',
        highlight && 'text-white font-medium',
        danger && 'text-red-400',
        !highlight && !danger && 'text-[#94a3b8]',
      )}>
        {value ?? '—'}
      </span>
    </div>
  )
}
