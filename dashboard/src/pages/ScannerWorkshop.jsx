import { useEffect, useState } from 'react'
import { Search, Play, Eye, Save, RotateCcw } from 'lucide-react'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Spinner from '../components/Spinner'
import {
  fetchOpportunities, fetchScannerConfig, updateScannerConfig,
  previewScanner, runScanner,
} from '../api'

const fmt = (n) => n == null ? '—' : `$${n.toLocaleString('en-US', { minimumFractionDigits: 2 })}`

export default function ScannerWorkshop() {
  const [opportunities, setOpportunities] = useState([])
  const [config, setConfig] = useState({})
  const [draft, setDraft] = useState({})
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [saving, setSaving] = useState(false)

  const load = async () => {
    try {
      const [opps, cfg] = await Promise.all([
        fetchOpportunities(),
        fetchScannerConfig(),
      ])
      setOpportunities(opps.opportunities || [])
      setConfig(cfg)
      setDraft({
        min_daily_volume: cfg.min_daily_volume || 1000000,
        min_price: cfg.min_price || 5,
        max_price: cfg.max_price || 500,
        min_iv_rank: cfg.min_iv_rank || 15,
        min_liquidity_score: cfg.min_liquidity_score || 0.3,
        top_n: cfg.top_n || 20,
        weights: { ...(cfg.weights || {}) },
      })
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleRunScan = async () => {
    setScanning(true)
    try {
      await runScanner()
      const opps = await fetchOpportunities()
      setOpportunities(opps.opportunities || [])
    } catch (e) {
      console.error(e)
    } finally {
      setScanning(false)
    }
  }

  const handlePreview = async () => {
    setPreviewing(true)
    try {
      const result = await previewScanner(draft)
      setPreview(result)
    } catch (e) {
      console.error(e)
    } finally {
      setPreviewing(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await updateScannerConfig(draft)
      setConfig({ ...config, ...draft })
      setPreview(null)
    } catch (e) {
      console.error(e)
    } finally {
      setSaving(false)
    }
  }

  const handleReset = () => {
    setDraft({
      min_daily_volume: config.min_daily_volume || 1000000,
      min_price: config.min_price || 5,
      max_price: config.max_price || 500,
      min_iv_rank: config.min_iv_rank || 15,
      min_liquidity_score: config.min_liquidity_score || 0.3,
      top_n: config.top_n || 20,
      weights: { ...(config.weights || {}) },
    })
    setPreview(null)
  }

  const updateDraft = (key, value) => {
    setDraft((d) => ({ ...d, [key]: value }))
  }

  const updateWeight = (key, value) => {
    setDraft((d) => ({
      ...d,
      weights: { ...d.weights, [key]: parseFloat(value) || 0 },
    }))
  }

  if (loading) return <Spinner />

  const displayOpps = preview?.opportunities || opportunities

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-white flex items-center gap-2">
          <Search size={24} /> Scanner Workshop
        </h2>
        <button
          onClick={handleRunScan}
          disabled={scanning}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
        >
          <Play size={14} className={scanning ? 'animate-pulse' : ''} />
          {scanning ? 'Scanning...' : 'Run Full Scan'}
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Parameter Panel */}
        <Card title="Parameters" subtitle="Tune and preview results live" className="lg:col-span-1">
          <div className="space-y-4">
            {/* Pre-filter */}
            <div>
              <h4 className="text-xs text-[#64748b] uppercase mb-2">Pre-filter</h4>
              <div className="space-y-2">
                <label className="block">
                  <span className="text-xs text-[#94a3b8]">Min Daily Volume</span>
                  <input
                    type="number"
                    value={draft.min_daily_volume}
                    onChange={(e) => updateDraft('min_daily_volume', parseInt(e.target.value))}
                    className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                  />
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <label className="block">
                    <span className="text-xs text-[#94a3b8]">Min Price</span>
                    <input
                      type="number"
                      value={draft.min_price}
                      onChange={(e) => updateDraft('min_price', parseFloat(e.target.value))}
                      className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                    />
                  </label>
                  <label className="block">
                    <span className="text-xs text-[#94a3b8]">Max Price</span>
                    <input
                      type="number"
                      value={draft.max_price}
                      onChange={(e) => updateDraft('max_price', parseFloat(e.target.value))}
                      className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                    />
                  </label>
                </div>
              </div>
            </div>

            {/* Scoring */}
            <div>
              <h4 className="text-xs text-[#64748b] uppercase mb-2">Scoring</h4>
              <div className="space-y-2">
                <label className="block">
                  <span className="text-xs text-[#94a3b8]">Min IV Rank</span>
                  <input
                    type="number"
                    step="1"
                    value={draft.min_iv_rank}
                    onChange={(e) => updateDraft('min_iv_rank', parseFloat(e.target.value))}
                    className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                  />
                </label>
                <label className="block">
                  <span className="text-xs text-[#94a3b8]">Min Liquidity Score</span>
                  <input
                    type="number"
                    step="0.05"
                    value={draft.min_liquidity_score}
                    onChange={(e) => updateDraft('min_liquidity_score', parseFloat(e.target.value))}
                    className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                  />
                </label>
                <label className="block">
                  <span className="text-xs text-[#94a3b8]">Top N Results</span>
                  <input
                    type="number"
                    value={draft.top_n}
                    onChange={(e) => updateDraft('top_n', parseInt(e.target.value))}
                    className="w-full mt-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                  />
                </label>
              </div>
            </div>

            {/* Weights */}
            <div>
              <h4 className="text-xs text-[#64748b] uppercase mb-2">Scoring Weights</h4>
              <div className="space-y-2">
                {Object.entries(draft.weights || {}).map(([key, val]) => (
                  <label key={key} className="flex items-center justify-between">
                    <span className="text-xs text-[#94a3b8] capitalize">{key.replace('_', ' ')}</span>
                    <input
                      type="number"
                      step="0.05"
                      value={val}
                      onChange={(e) => updateWeight(key, e.target.value)}
                      className="w-20 bg-[#0f172a] border border-[#334155] rounded-lg px-2 py-1.5 text-sm text-white text-right focus:outline-none focus:border-blue-500"
                    />
                  </label>
                ))}
              </div>
            </div>

            {/* Actions */}
            <div className="flex gap-2 pt-2">
              <button
                onClick={handlePreview}
                disabled={previewing}
                className="flex-1 flex items-center justify-center gap-1 px-3 py-2 bg-[#334155] hover:bg-[#475569] text-white text-sm rounded-lg transition-colors disabled:opacity-50"
              >
                <Eye size={14} /> {previewing ? 'Loading...' : 'Preview'}
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex-1 flex items-center justify-center gap-1 px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
              >
                <Save size={14} /> Save
              </button>
              <button
                onClick={handleReset}
                className="px-3 py-2 bg-[#334155] hover:bg-[#475569] text-[#94a3b8] text-sm rounded-lg transition-colors"
              >
                <RotateCcw size={14} />
              </button>
            </div>
          </div>
        </Card>

        {/* Results */}
        <Card
          title={preview ? 'Preview Results' : 'Scanner Results'}
          subtitle={`${displayOpps.length} opportunities`}
          className="lg:col-span-2"
        >
          {preview && (
            <div className="mb-3 px-3 py-2 bg-yellow-500/10 border border-yellow-500/20 rounded-lg text-xs text-yellow-400">
              ⚠ Preview mode — showing results with your draft parameters (not saved yet)
            </div>
          )}

          {displayOpps.length === 0 ? (
            <p className="text-sm text-[#64748b] text-center py-8">
              No opportunities. Run a scan to populate results.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[#64748b] text-xs uppercase border-b border-[#334155]">
                    <th className="text-left py-3 px-2">#</th>
                    <th className="text-left py-3 px-2">Symbol</th>
                    <th className="text-left py-3 px-2">Type</th>
                    <th className="text-right py-3 px-2">Score</th>
                    <th className="text-right py-3 px-2">IV Rank</th>
                    <th className="text-right py-3 px-2">Mom 30d</th>
                    <th className="text-center py-3 px-2">Support</th>
                    <th className="text-right py-3 px-2">Liquidity</th>
                  </tr>
                </thead>
                <tbody>
                  {displayOpps.map((o, i) => (
                    <tr key={o.symbol || i} className="border-b border-[#334155]/50 hover:bg-[#334155]/30">
                      <td className="py-3 px-2 text-[#64748b]">{i + 1}</td>
                      <td className="py-3 px-2 font-medium text-white">{o.symbol}</td>
                      <td className="py-3 px-2">
                        <Badge variant={o.asset_type === 'etf' ? 'yellow' : 'blue'}>
                          {o.asset_type || 'stock'}
                        </Badge>
                      </td>
                      <td className="py-3 px-2 text-right font-mono text-blue-400">
                        {(o.composite_score || 0).toFixed(3)}
                      </td>
                      <td className="py-3 px-2 text-right">{(o.iv_rank || 0).toFixed(0)}</td>
                      <td className={`py-3 px-2 text-right ${(o.momentum_30d || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {((o.momentum_30d || 0) * 100).toFixed(1)}%
                      </td>
                      <td className="py-3 px-2 text-center">
                        {o.near_support ? '✅' : '—'}
                      </td>
                      <td className="py-3 px-2 text-right">
                        {(o.options_liquidity_score || 0).toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
