import { useEffect, useState } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts'
import {
  DollarSign, TrendingUp, Wallet, Shield, RefreshCw,
} from 'lucide-react'
import StatCard from '../components/StatCard'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Spinner from '../components/Spinner'
import ActivePositions from '../components/ActivePositions'
import { fetchPortfolioSummary, fetchPortfolio, refreshPortfolio } from '../api'

const fmt = (n) => {
  if (n == null) return '—'
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 })
}

const pct = (n) => {
  if (n == null) return '—'
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

export default function Portfolio() {
  const [data, setData] = useState(null)
  const [options, setOptions] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const load = async () => {
    try {
      const [summary, full] = await Promise.all([
        fetchPortfolioSummary(),
        fetchPortfolio(),
      ])
      setData(summary)
      setOptions(full.options || [])
    } catch (e) {
      console.error('Portfolio load failed:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  // Re-fetch when trading mode changes (account balances differ)
  useEffect(() => {
    const handler = () => {
      setLoading(true)
      load()
    }
    window.addEventListener('trading-mode-changed', handler)
    return () => window.removeEventListener('trading-mode-changed', handler)
  }, [])

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await refreshPortfolio()
      await load()
    } finally {
      setRefreshing(false)
    }
  }

  if (loading) return <Spinner />

  const regime = data?.regime || {}
  const regimeColor =
    regime.regime === 'high_vol' ? 'red' :
    regime.regime === 'low_vol' ? 'green' : 'blue'

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Portfolio Overview</h2>
          <p className="text-sm text-[#64748b]">
            Last updated: {data?.last_updated ? new Date(data.last_updated).toLocaleString() : '—'}
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
        >
          <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Equity"
          value={fmt(data?.equity)}
          icon={DollarSign}
        />
        <StatCard
          label="Cash"
          value={fmt(data?.cash)}
          icon={Wallet}
        />
        <StatCard
          label="Buying Power"
          value={fmt(data?.buying_power)}
          icon={TrendingUp}
        />
        <StatCard
          label="Total Value"
          value={fmt(data?.total_value)}
          icon={Shield}
        />
      </div>

      {/* Second row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Unrealized P&L"
          value={fmt(data?.total_unrealized_pnl)}
          trend={data?.total_unrealized_pnl > 0 ? 'up' : data?.total_unrealized_pnl < 0 ? 'down' : null}
        />
        <StatCard
          label="Option P&L"
          value={fmt(data?.total_option_pnl)}
          trend={data?.total_option_pnl > 0 ? 'up' : data?.total_option_pnl < 0 ? 'down' : null}
        />
        <StatCard
          label="Premium Collected"
          value={fmt(data?.total_premium_collected)}
          trend="up"
        />
        <StatCard
          label="Open Positions"
          value={`${data?.stock_positions || 0} stocks · ${data?.short_options || 0} short opts`}
        />
      </div>

      {/* Active Positions */}
      <ActivePositions options={options} />

      {/* Market Regime */}
      <Card title="Market Regime" subtitle="VIX-based regime detection">
        <div className="flex items-center gap-4">
          <Badge variant={regimeColor}>
            {regime.regime?.replace('_', ' ').toUpperCase() || 'UNKNOWN'}
          </Badge>
          <span className="text-sm text-[#94a3b8]">
            VIX ≈ {regime.vix_level?.toFixed(1) || '—'}
          </span>
          <span className="text-xs text-[#64748b]">
            {regime.adjustments || ''}
          </span>
        </div>
        {regime.last_refresh && (
          <p className="text-xs text-[#64748b] mt-2">
            Last refresh: {new Date(regime.last_refresh).toLocaleString()}
          </p>
        )}
      </Card>
    </div>
  )
}
