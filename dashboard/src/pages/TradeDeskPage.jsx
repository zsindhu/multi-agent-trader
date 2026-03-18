import { useEffect, useState, useCallback } from 'react'
import {
  Play, Zap, ChevronDown, ChevronRight, CheckCircle, XCircle,
  Search, Eye, Save, RotateCcw, Undo2, Loader,
} from 'lucide-react'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Spinner from '../components/Spinner'
import ProposalCard from '../components/ProposalCard'
import {
  fetchOpportunities, fetchScannerConfig, updateScannerConfig,
  previewScanner, runScanner,
  fetchPendingProposals, generateProposals, approveBatch, rejectBatch,
  fetchPortfolioSummary, fetchAlpacaOrders,
} from '../api'

// ── Scanner slider/weight defs (same as ScannerWorkshop) ────────────
const PARAM_DEFS = [
  { key: 'min_daily_volume', label: 'Min Daily Volume', group: 'prefilter', min: 100_000, max: 5_000_000, step: 100_000, format: (v) => `${(v / 1_000_000).toFixed(1)}M` },
  { key: 'min_price',        label: 'Min Price',        group: 'prefilter', min: 1,       max: 50,        step: 1,       format: (v) => `$${v}` },
  { key: 'max_price',        label: 'Max Price',        group: 'prefilter', min: 50,      max: 1000,      step: 10,      format: (v) => `$${v}` },
  { key: 'min_iv_rank',      label: 'Min IV Rank',      group: 'scoring',   min: 0,       max: 100,       step: 1,       format: (v) => `${v}` },
  { key: 'min_liquidity_score', label: 'Min Liquidity', group: 'scoring',   min: 0,       max: 1,         step: 0.05,    format: (v) => `${v.toFixed(2)}` },
  { key: 'top_n',            label: 'Top N Results',    group: 'scoring',   min: 5,       max: 50,        step: 1,       format: (v) => `${v}` },
]
const WEIGHT_KEYS = ['iv_rank', 'momentum', 'liquidity', 'support_proximity', 'mean_reversion']
const WEIGHT_LABELS = { iv_rank: 'IV Rank', momentum: 'Momentum', liquidity: 'Liquidity', support_proximity: 'Support Prox.', mean_reversion: 'Mean Reversion' }

function ParamSlider({ label, value, defaultValue, min, max, step, format, onChange, onReset }) {
  const isModified = value !== defaultValue
  const defaultPct = ((defaultValue - min) / (max - min)) * 100
  return (
    <div className="py-2">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span className={`text-xs font-medium ${isModified ? 'text-amber-400' : 'text-[#94a3b8]'}`}>{label}</span>
          {isModified && <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">modified</span>}
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-sm font-mono ${isModified ? 'text-amber-400' : 'text-white'}`}>{format(value)}</span>
          <span className="text-[10px] text-[#475569]">def: {format(defaultValue)}</span>
          {isModified && <button onClick={onReset} className="p-0.5 text-[#64748b] hover:text-amber-400"><Undo2 size={12} /></button>}
        </div>
      </div>
      <div className="relative h-6 flex items-center">
        <div className="absolute top-0 bottom-0 flex items-center pointer-events-none z-10" style={{ left: `${defaultPct}%`, transform: 'translateX(-50%)' }}>
          <div className="w-0.5 h-3 bg-[#64748b] rounded-full" />
        </div>
        <input type="range" min={min} max={max} step={step} value={value} onChange={e => onChange(parseFloat(e.target.value))}
          className="w-full h-1.5 appearance-none bg-[#334155] rounded-full cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-blue-400" />
      </div>
    </div>
  )
}

function WeightBar({ label, value, defaultValue, onChange, onReset }) {
  const isModified = Math.abs(value - defaultValue) > 0.001
  const maxVal = 0.60
  return (
    <div className="py-1.5">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-1">
          <span className={`text-xs ${isModified ? 'text-amber-400' : 'text-[#94a3b8]'}`}>{label}</span>
          {isModified && <button onClick={onReset} className="text-[#64748b] hover:text-amber-400"><Undo2 size={10} /></button>}
        </div>
        <span className={`text-xs font-mono ${isModified ? 'text-amber-400' : 'text-white'}`}>{(value * 100).toFixed(0)}%</span>
      </div>
      <div className="relative h-3 bg-[#1e293b] rounded overflow-hidden">
        <div className="absolute inset-y-0 left-0 bg-blue-500/15 rounded" style={{ width: `${Math.min((defaultValue / maxVal) * 100, 100)}%` }} />
        <div className={`absolute inset-y-0 left-0 rounded ${isModified ? 'bg-amber-500/40' : 'bg-blue-500/40'}`} style={{ width: `${Math.min((value / maxVal) * 100, 100)}%` }} />
      </div>
      <input type="range" min={0} max={0.60} step={0.05} value={value} onChange={e => onChange(parseFloat(e.target.value))}
        className="w-full h-1 -mt-2 appearance-none bg-transparent cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-2.5 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:border [&::-webkit-slider-thumb]:border-blue-400/60" />
    </div>
  )
}

// ── Main Component ───────────────────────────────────────────────────
export default function TradeDeskPage() {
  // Scanner state
  const [opportunities, setOpportunities] = useState([])
  const [scannerConfig, setScannerConfig] = useState({})
  const [scannerDefaults, setScannerDefaults] = useState({})
  const [draft, setDraft] = useState({})
  const [scannerPreview, setScannerPreview] = useState(null)
  const [tunerOpen, setTunerOpen] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [lastScanTime, setLastScanTime] = useState(null)
  const [scanError, setScanError] = useState(null)

  // Proposals state
  const [proposals, setProposals] = useState([])
  const [batchId, setBatchId] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [approving, setApproving] = useState(false)
  const [rejecting, setRejecting] = useState(false)

  // Portfolio impact
  const [portfolioSummary, setPortfolioSummary] = useState(null)

  // Execution feed
  const [executedProposals, setExecutedProposals] = useState([])

  // Alpaca order history
  const [alpacaOrders, setAlpacaOrders] = useState([])
  const [ordersLoading, setOrdersLoading] = useState(false)
  const [ordersOpen, setOrdersOpen] = useState(false)

  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const [opps, cfgResp, pending, ps] = await Promise.all([
        fetchOpportunities(),
        fetchScannerConfig(),
        fetchPendingProposals(),
        fetchPortfolioSummary(),
      ])
      setOpportunities(opps.opportunities || [])
      setPortfolioSummary(ps)

      const current = cfgResp.current || cfgResp
      const defaults = cfgResp.defaults || {}
      setScannerConfig(current)
      setScannerDefaults(defaults)
      setDraft({
        min_daily_volume: current.min_daily_volume ?? defaults.min_daily_volume ?? 1_000_000,
        min_price: current.min_price ?? defaults.min_price ?? 5,
        max_price: current.max_price ?? defaults.max_price ?? 500,
        min_iv_rank: current.min_iv_rank ?? defaults.min_iv_rank ?? 15,
        min_liquidity_score: current.min_liquidity_score ?? defaults.min_liquidity_score ?? 0.3,
        top_n: current.top_n ?? defaults.top_n ?? 20,
        weights: { ...(defaults.weights || {}), ...(current.weights || {}) },
      })

      setProposals(pending)
      if (pending.length > 0) setBatchId(pending[0].batch_id)
    } catch (e) {
      console.error('Trade Desk load failed:', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // ── Scanner actions ──────────────────────────────────────────────
  const handleRunScan = async () => {
    setScanning(true)
    setScanError(null)
    try {
      await runScanner()
      const opps = await fetchOpportunities()
      setOpportunities(opps.opportunities || [])
      setLastScanTime(new Date())
    } catch (e) {
      setScanError(e.message || 'Scan failed')
    } finally {
      setScanning(false)
    }
  }

  const handlePreview = async () => {
    setPreviewing(true)
    try { setScannerPreview(await previewScanner(draft)) }
    catch (e) { console.error(e) }
    finally { setPreviewing(false) }
  }

  const handleSaveScannerConfig = async () => {
    setSaving(true)
    try { await updateScannerConfig(draft); setScannerPreview(null) }
    catch (e) { console.error(e) }
    finally { setSaving(false) }
  }

  const updateDraft = (key, value) => setDraft(d => ({ ...d, [key]: value }))
  const updateWeight = (key, value) => setDraft(d => ({ ...d, weights: { ...d.weights, [key]: value } }))

  const resetAll = () => {
    setDraft({
      min_daily_volume: scannerDefaults.min_daily_volume ?? 1_000_000,
      min_price: scannerDefaults.min_price ?? 5,
      max_price: scannerDefaults.max_price ?? 500,
      min_iv_rank: scannerDefaults.min_iv_rank ?? 15,
      min_liquidity_score: scannerDefaults.min_liquidity_score ?? 0.3,
      top_n: scannerDefaults.top_n ?? 20,
      weights: { ...(scannerDefaults.weights || {}) },
    })
    setScannerPreview(null)
  }

  // ── Proposal actions ─────────────────────────────────────────────
  const handleGenerate = async () => {
    setGenerating(true)
    try {
      const result = await generateProposals()
      setProposals(result.proposals || [])
      setBatchId(result.batch_id)
    } catch (e) {
      alert('Failed to generate proposals: ' + (e.message || 'Unknown error'))
    } finally {
      setGenerating(false)
    }
  }

  const handleProposalUpdate = (updated) => {
    setProposals(prev =>
      prev.map(p => p.id === updated.id ? updated : p)
    )
    if (updated.status === 'executed') {
      setExecutedProposals(prev => [updated, ...prev])
    }
  }

  const handleLoadOrders = async () => {
    setOrdersLoading(true)
    try {
      const orders = await fetchAlpacaOrders(30)
      setAlpacaOrders(orders)
      setOrdersOpen(true)
    } catch (e) {
      console.error('Failed to load Alpaca orders:', e)
    } finally {
      setOrdersLoading(false)
    }
  }

  const handleApproveAll = async () => {
    if (!batchId) return
    setApproving(true)
    try {
      const results = await approveBatch(batchId)
      results.forEach(handleProposalUpdate)
    } catch (e) {
      alert('Batch approve failed: ' + e.message)
    } finally {
      setApproving(false)
    }
  }

  const handleRejectAll = async () => {
    if (!batchId) return
    setRejecting(true)
    try {
      const results = await rejectBatch(batchId)
      results.forEach(handleProposalUpdate)
    } catch (e) {
      alert('Batch reject failed: ' + e.message)
    } finally {
      setRejecting(false)
    }
  }

  // ── Derived ──────────────────────────────────────────────────────
  const displayOpps = scannerPreview?.opportunities || opportunities
  const pendingProposals = proposals.filter(p => p.status === 'pending')
  const doneProposals = proposals.filter(p => p.status !== 'pending')

  const portfolioImpact = pendingProposals.reduce((acc, p) => {
    acc.collateral += p.collateral_required || 0
    acc.premium += p.total_premium || 0
    return acc
  }, { collateral: 0, premium: 0 })

  const buyingPower = portfolioSummary?.buying_power || 0
  const collateralPct = buyingPower > 0 ? ((portfolioImpact.collateral / buyingPower) * 100).toFixed(1) : '—'
  const remainingAfterAll = buyingPower > 0 ? buyingPower - portfolioImpact.collateral : null

  // Per-card remaining buying power: decreases as we walk down the proposal list
  // so each card knows how much is left after the proposals above it
  function getRemainingBefore(index) {
    if (buyingPower <= 0) return null
    let used = 0
    for (let i = 0; i < index; i++) {
      used += pendingProposals[i].collateral_required || 0
    }
    return buyingPower - used
  }

  const prefilterParams = PARAM_DEFS.filter(p => p.group === 'prefilter')
  const scoringParams = PARAM_DEFS.filter(p => p.group === 'scoring')

  const firstTime = opportunities.length === 0 && proposals.length === 0

  if (loading) return <div className="flex items-center justify-center h-64"><Spinner /></div>

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-white">Trade Desk</h2>
        <p className="text-sm text-[#64748b]">Scan → Propose → Review → Execute. Nothing trades without your approval.</p>
      </div>

      {/* ── First-time onboarding ── */}
      {firstTime && (
        <Card>
          <div className="py-6">
            <h3 className="text-base font-semibold text-white mb-4">Get started in 4 steps</h3>
            <div className="flex flex-col sm:flex-row gap-3">
              {[
                { n: '①', label: 'Connected', desc: `Paper account ${portfolioSummary?.cash != null ? `· $${Math.round(portfolioSummary.cash).toLocaleString()} cash` : ''}`, done: true },
                { n: '②', label: 'Run Scanner', desc: 'Find tradable opportunities', done: opportunities.length > 0 },
                { n: '③', label: 'Generate Proposals', desc: 'Lead Agent picks the best contracts', done: proposals.length > 0 },
                { n: '④', label: 'Review & Approve', desc: 'You decide what executes', done: false },
              ].map(step => (
                <div key={step.n} className={`flex-1 rounded-lg p-3 border ${step.done ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-[#1e293b] bg-[#0a0f1e]'}`}>
                  <div className="text-lg mb-1">{step.n}</div>
                  <div className={`text-sm font-medium ${step.done ? 'text-emerald-400' : 'text-white'}`}>{step.label}</div>
                  <div className="text-xs text-[#64748b] mt-0.5">{step.desc}</div>
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}

      {/* ═══════════════════════════════════════════════════════════════
          SECTION A — Market Scanner
      ═══════════════════════════════════════════════════════════════ */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-white flex items-center gap-2">
              <Search size={18} className="text-amber-400" /> Market Scanner
            </h3>
            {lastScanTime && (
              <p className="text-xs text-[#64748b] mt-0.5">Last scan: {lastScanTime.toLocaleTimeString()}</p>
            )}
          </div>
          <div className="flex flex-col items-end gap-1">
            <div className="flex items-center gap-2">
              <button
                onClick={() => setTunerOpen(v => !v)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-[#334155] text-[#94a3b8] hover:text-white hover:border-[#64748b] rounded-lg transition-colors"
              >
                {tunerOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                Tune Scanner
              </button>
              <button
                onClick={handleRunScan}
                disabled={scanning}
                className="flex items-center gap-2 px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
              >
                {scanning ? <Loader size={14} className="animate-spin" /> : <Play size={14} />}
                {scanning ? 'Scanning...' : 'Run Scan'}
              </button>
            </div>
            {scanError && (
              <p className="text-xs text-red-400">{scanError}</p>
            )}
          </div>
        </div>

        {/* Collapsible Tune Scanner panel */}
        {tunerOpen && (
          <Card className="border-amber-500/20">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Prefilter */}
              <div className="space-y-1">
                <h4 className="text-xs text-[#64748b] uppercase font-semibold tracking-wider mb-2">Pre-filter</h4>
                {prefilterParams.map(p => (
                  <ParamSlider key={p.key} label={p.label}
                    value={draft[p.key] ?? 0} defaultValue={scannerDefaults[p.key] ?? 0}
                    min={p.min} max={p.max} step={p.step} format={p.format}
                    onChange={v => updateDraft(p.key, v)} onReset={() => updateDraft(p.key, scannerDefaults[p.key])} />
                ))}
              </div>
              {/* Scoring */}
              <div className="space-y-1">
                <h4 className="text-xs text-[#64748b] uppercase font-semibold tracking-wider mb-2">Scoring</h4>
                {scoringParams.map(p => (
                  <ParamSlider key={p.key} label={p.label}
                    value={draft[p.key] ?? 0} defaultValue={scannerDefaults[p.key] ?? 0}
                    min={p.min} max={p.max} step={p.step} format={p.format}
                    onChange={v => updateDraft(p.key, v)} onReset={() => updateDraft(p.key, scannerDefaults[p.key])} />
                ))}
              </div>
              {/* Weights */}
              <div className="space-y-1">
                <h4 className="text-xs text-[#64748b] uppercase font-semibold tracking-wider mb-2">Weights</h4>
                {WEIGHT_KEYS.map(k => (
                  <WeightBar key={k} label={WEIGHT_LABELS[k]}
                    value={draft.weights?.[k] ?? 0} defaultValue={scannerDefaults.weights?.[k] ?? 0}
                    onChange={v => updateWeight(k, v)} onReset={() => updateWeight(k, scannerDefaults.weights?.[k] ?? 0)} />
                ))}
              </div>
            </div>
            <div className="flex items-center gap-2 mt-4 pt-4 border-t border-[#334155]">
              <button onClick={resetAll} className="flex items-center gap-1 px-3 py-1.5 text-xs text-amber-400 border border-amber-500/20 rounded hover:bg-amber-500/10 transition-colors">
                <RotateCcw size={10} /> Reset All
              </button>
              <button onClick={handlePreview} disabled={previewing} className="flex items-center gap-1 px-3 py-1.5 text-sm bg-[#334155] hover:bg-[#475569] text-white rounded-lg transition-colors disabled:opacity-50">
                <Eye size={14} /> {previewing ? 'Loading...' : 'Preview'}
              </button>
              <button onClick={handleSaveScannerConfig} disabled={saving} className="flex items-center gap-1 px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors disabled:opacity-50">
                <Save size={14} /> Save Config
              </button>
              {scannerPreview && <span className="text-xs text-amber-400 ml-1">Showing preview results</span>}
            </div>
          </Card>
        )}

        {/* Scanner Results Table */}
        {displayOpps.length === 0 ? (
          <Card>
            <div className="py-10 text-center space-y-3">
              <Search size={32} className="mx-auto text-[#334155]" />
              <p className="text-sm text-white font-medium">
                {lastScanTime ? 'No opportunities found' : 'No scan results yet'}
              </p>
              <p className="text-xs text-[#64748b]">
                {lastScanTime
                  ? `Scan at ${lastScanTime.toLocaleTimeString()} — no symbols met the current filters. Try loosening the thresholds in Tune Scanner.`
                  : 'Click "Run Scan" to discover tradable opportunities.'
                }
              </p>
              <button
                onClick={handleRunScan}
                disabled={scanning}
                className="mx-auto flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
              >
                {scanning ? <Loader size={14} className="animate-spin" /> : <Play size={14} />}
                {scanning ? 'Scanning...' : 'Run Your First Scan'}
              </button>
            </div>
          </Card>
        ) : (
          <Card title={`${displayOpps.length} Opportunities`} subtitle={scannerPreview ? 'Preview mode' : 'Live scanner results'}>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[#64748b] text-xs uppercase border-b border-[#334155]">
                    <th className="text-left py-2.5 px-2">#</th>
                    <th className="text-left py-2.5 px-2">Symbol</th>
                    <th className="text-left py-2.5 px-2">Type</th>
                    <th className="text-right py-2.5 px-2">Score</th>
                    <th className="text-right py-2.5 px-2">IV Rank</th>
                    <th className="text-right py-2.5 px-2">Mom 30d</th>
                    <th className="text-center py-2.5 px-2">Support</th>
                    <th className="text-right py-2.5 px-2">Liquidity</th>
                  </tr>
                </thead>
                <tbody>
                  {displayOpps.map((o, i) => (
                    <tr key={o.symbol || i} className="border-b border-[#334155]/40 hover:bg-[#334155]/20 transition-colors">
                      <td className="py-2.5 px-2 text-[#64748b]">{i + 1}</td>
                      <td className="py-2.5 px-2 font-medium text-white font-mono">{o.symbol}</td>
                      <td className="py-2.5 px-2">
                        <Badge variant={o.asset_type === 'etf' ? 'yellow' : 'blue'}>{o.asset_type || 'stock'}</Badge>
                      </td>
                      <td className="py-2.5 px-2 text-right font-mono text-blue-400">{(o.composite_score || 0).toFixed(3)}</td>
                      <td className="py-2.5 px-2 text-right text-white">{(o.iv_rank || 0).toFixed(0)}</td>
                      <td className={`py-2.5 px-2 text-right ${(o.momentum_30d || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {(o.momentum_30d || 0).toFixed(1)}%
                      </td>
                      <td className="py-2.5 px-2 text-center">{o.near_support ? '✓' : '—'}</td>
                      <td className="py-2.5 px-2 text-right text-[#94a3b8]">{(o.options_liquidity_score || 0).toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </section>

      {/* ═══════════════════════════════════════════════════════════════
          SECTION B — Trade Proposals
      ═══════════════════════════════════════════════════════════════ */}
      <section className="space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h3 className="text-lg font-semibold text-white flex items-center gap-2">
              <Zap size={18} className="text-emerald-400" /> Proposed Trades
            </h3>
            {batchId && (
              <p className="text-xs text-[#64748b] mt-0.5">
                Batch {batchId.slice(0, 8)} · {pendingProposals.length} pending
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {pendingProposals.length > 0 && (
              <>
                <button
                  onClick={handleRejectAll}
                  disabled={rejecting || approving}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-red-500/30 text-red-400 hover:bg-red-500/10 rounded-lg transition-colors disabled:opacity-50"
                >
                  <XCircle size={14} /> {rejecting ? 'Rejecting...' : 'Reject All'}
                </button>
                <button
                  onClick={handleApproveAll}
                  disabled={approving || rejecting}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-emerald-500/20 border border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/30 rounded-lg transition-colors disabled:opacity-50"
                >
                  <CheckCircle size={14} /> {approving ? 'Approving...' : 'Approve All'}
                </button>
              </>
            )}
            <button
              onClick={handleGenerate}
              disabled={generating || opportunities.length === 0}
              className="flex items-center gap-2 px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
              title={opportunities.length === 0 ? 'Run Scanner first' : ''}
            >
              {generating ? <Loader size={14} className="animate-spin" /> : <Zap size={14} />}
              {generating ? 'Generating...' : 'Generate Proposals'}
            </button>
          </div>
        </div>

        {proposals.length === 0 ? (
          <Card>
            <div className="py-10 text-center space-y-3">
              <Zap size={32} className="mx-auto text-[#334155]" />
              <p className="text-sm text-white font-medium">No proposals yet</p>
              <p className="text-xs text-[#64748b] max-w-xs mx-auto">
                {opportunities.length === 0
                  ? 'Run the Scanner first to discover opportunities, then click Generate Proposals.'
                  : 'Click "Generate Proposals" to see what the Lead Agent recommends. Nothing executes until you approve.'}
              </p>
              {opportunities.length > 0 && (
                <button
                  onClick={handleGenerate}
                  disabled={generating}
                  className="mx-auto flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
                >
                  {generating ? <Loader size={14} className="animate-spin" /> : <Zap size={14} />}
                  Generate Proposals
                </button>
              )}
            </div>
          </Card>
        ) : (
          <div className="space-y-3">
            {/* Capital summary banner */}
            {pendingProposals.length > 0 && buyingPower > 0 && (
              <div className="px-4 py-3 bg-[#0a0f1e] rounded-xl border border-[#1e293b]">
                <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
                  <div>
                    <span className="text-[#64748b] text-xs uppercase tracking-wider">Available</span>
                    <p className="text-white font-medium font-mono">${buyingPower.toLocaleString('en-US', { minimumFractionDigits: 0 })}</p>
                  </div>
                  <div>
                    <span className="text-[#64748b] text-xs uppercase tracking-wider">Would deploy</span>
                    <p className="text-amber-400 font-medium font-mono">
                      ${portfolioImpact.collateral.toLocaleString('en-US', { minimumFractionDigits: 0 })}
                      {collateralPct !== '—' && <span className="text-xs text-[#64748b] ml-1">({collateralPct}%)</span>}
                    </p>
                  </div>
                  <div>
                    <span className="text-[#64748b] text-xs uppercase tracking-wider">Remaining</span>
                    <p className={`font-medium font-mono ${remainingAfterAll != null && remainingAfterAll < 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                      ${Math.max(remainingAfterAll ?? 0, 0).toLocaleString('en-US', { minimumFractionDigits: 0 })}
                    </p>
                  </div>
                  <div>
                    <span className="text-[#64748b] text-xs uppercase tracking-wider">Est. premium</span>
                    <p className="text-emerald-400 font-medium font-mono">+${portfolioImpact.premium.toLocaleString('en-US', { minimumFractionDigits: 0 })}</p>
                  </div>
                </div>
                {remainingAfterAll != null && remainingAfterAll < 0 && (
                  <p className="text-xs text-red-400 mt-2">
                    ⚠ Proposals exceed buying power by ${Math.abs(remainingAfterAll).toLocaleString('en-US', { minimumFractionDigits: 0 })} — some will show as insufficient
                  </p>
                )}
              </div>
            )}

            {/* Pending */}
            {pendingProposals.map((p, i) => (
              <ProposalCard
                key={p.id}
                proposal={p}
                onUpdate={handleProposalUpdate}
                remainingBuyingPower={getRemainingBefore(i)}
              />
            ))}

            {/* Completed proposals (collapsed) */}
            {doneProposals.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs text-[#64748b] uppercase font-semibold tracking-wider">Completed</p>
                {doneProposals.map(p => (
                  <ProposalCard key={p.id} proposal={p} onUpdate={handleProposalUpdate} />
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      {/* ═══════════════════════════════════════════════════════════════
          SECTION C — Execution Status
      ═══════════════════════════════════════════════════════════════ */}
      {executedProposals.length > 0 && (
        <section className="space-y-3">
          <h3 className="text-lg font-semibold text-white flex items-center gap-2">
            <CheckCircle size={18} className="text-blue-400" /> Execution Status
          </h3>
          <div className="space-y-2">
            {executedProposals.map(p => (
              <div key={p.id} className="flex items-center gap-3 px-4 py-3 bg-[#111827] rounded-xl border border-emerald-500/20">
                <CheckCircle size={16} className="text-emerald-400 flex-shrink-0" />
                <span className="text-sm text-white font-mono font-medium">{p.symbol}</span>
                <Badge variant="green">{p.contract_type?.toUpperCase()} ${p.strike}</Badge>
                <span className="text-xs text-[#64748b]">exp {p.expiration}</span>
                <span className="text-emerald-400 text-sm ml-auto font-medium">
                  +${p.total_premium?.toFixed(0)} premium
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ═══════════════════════════════════════════════════════════════
          SECTION D — Alpaca Order History (diagnostic)
      ═══════════════════════════════════════════════════════════════ */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <button
            onClick={() => ordersOpen ? setOrdersOpen(false) : handleLoadOrders()}
            className="flex items-center gap-2 text-sm text-[#64748b] hover:text-white transition-colors"
          >
            {ordersOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            <span className="font-medium">Alpaca Order History</span>
            <span className="text-[10px] uppercase tracking-wider text-[#475569]">diagnostic</span>
          </button>
          {ordersOpen && (
            <button
              onClick={handleLoadOrders}
              disabled={ordersLoading}
              className="flex items-center gap-1 px-2.5 py-1 text-xs rounded border border-[#334155] text-[#94a3b8] hover:text-white hover:border-[#64748b] transition-colors disabled:opacity-50"
            >
              <RotateCcw size={11} className={ordersLoading ? 'animate-spin' : ''} />
              Refresh
            </button>
          )}
        </div>

        {ordersOpen && (
          <div className="bg-[#111827] rounded-xl border border-[#1e293b] overflow-hidden">
            {alpacaOrders.length === 0 ? (
              <p className="px-5 py-6 text-sm text-[#64748b] text-center">
                {ordersLoading ? 'Loading...' : 'No orders found in Alpaca.'}
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-[#64748b] text-[10px] uppercase tracking-wider border-b border-[#1e293b]">
                      <th className="text-left px-4 py-2.5">Symbol</th>
                      <th className="text-left px-4 py-2.5">Side</th>
                      <th className="text-right px-4 py-2.5">Qty</th>
                      <th className="text-left px-4 py-2.5">Status</th>
                      <th className="text-right px-4 py-2.5">Limit $</th>
                      <th className="text-right px-4 py-2.5">Fill $</th>
                      <th className="text-right px-4 py-2.5">Submitted</th>
                    </tr>
                  </thead>
                  <tbody>
                    {alpacaOrders.map((o, i) => {
                      const status = String(o.status || '').toLowerCase().replace('orderstatus.', '')
                      const statusColor =
                        status === 'filled' ? 'text-emerald-400' :
                        status === 'rejected' || status === 'canceled' ? 'text-red-400' :
                        status === 'held' ? 'text-amber-400' :
                        'text-[#94a3b8]'
                      const submittedAt = o.submitted_at
                        ? new Date(o.submitted_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
                        : '—'
                      return (
                        <tr key={o.order_id || i} className="border-b border-[#1e293b]/60 hover:bg-[#1e293b]/30 transition-colors">
                          <td className="px-4 py-2.5 font-mono text-white text-xs">{o.symbol}</td>
                          <td className="px-4 py-2.5 text-[#94a3b8] text-xs">{String(o.side || '').replace('OrderSide.', '')}</td>
                          <td className="px-4 py-2.5 text-right text-white text-xs">{o.qty}</td>
                          <td className={`px-4 py-2.5 text-xs font-medium ${statusColor}`}>{status}</td>
                          <td className="px-4 py-2.5 text-right text-[#94a3b8] text-xs font-mono">
                            {o.limit_price != null ? `$${Number(o.limit_price).toFixed(2)}` : '—'}
                          </td>
                          <td className="px-4 py-2.5 text-right text-[#94a3b8] text-xs font-mono">
                            {o.filled_avg_price != null ? `$${Number(o.filled_avg_price).toFixed(2)}` : '—'}
                          </td>
                          <td className="px-4 py-2.5 text-right text-[#64748b] text-xs">{submittedAt}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
