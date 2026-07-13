/**
 * Pipeline (design 3a) — expanded funnel spine, today's promotions with
 * expandable signal reasoning, signal fire rates, scan schedule, near misses.
 * All data real; honest '--' / empty states where the API has no answer.
 */
import { useState, useEffect } from 'react'
import Panel from '../components/Panel'
import SpineStrip from '../components/SpineStrip'
import { SleeveBadge, BarMeter } from '../components/bits'
import { MONO, UI, fmtTimeET } from '../lib/design'
import {
  fetchDashboardStatus,
  fetchDashboardPromotions,
  fetchDashboardSignals,
  fetchDashboardCycles,
} from '../api'

// ── helpers ──────────────────────────────────────────────────

const TH = {
  background: '#000080', color: '#fff', fontFamily: UI, fontSize: 11,
  padding: '2px 6px', textAlign: 'left', border: '1px solid #808080', whiteSpace: 'nowrap',
}
const TD = { padding: '2px 6px', border: '1px solid #c0c0c0' }
const MUTED = { fontFamily: UI, fontSize: 10, color: '#808080' }

function etMinutes(iso) {
  if (!iso) return null
  const et = new Date(new Date(iso).getTime() - 4 * 3600 * 1000)
  return et.getUTCHours() * 60 + et.getUTCMinutes()
}

function fmtNum(v, dp = 3) {
  return v == null ? '--' : Number(v).toFixed(dp)
}

function promotionsEmptyText() {
  const et = new Date(Date.now() - 4 * 3600 * 1000)
  const day = et.getUTCDay()
  if (day === 0 || day === 6) return 'No promotions today — first sweep 08:00 ET Monday'
  return 'No promotions yet today — Tier 1 sweep runs 08:00 ET'
}

// ── promotions table ─────────────────────────────────────────

function SignalChip({ name, sig }) {
  const fired = !!sig?.fired
  return (
    <div style={{
      fontFamily: MONO, fontSize: 10, padding: '1px 4px',
      border: `1px solid ${fired ? '#008000' : '#d0d0d0'}`,
      background: fired ? '#e8ffe8' : '#fff',
      whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
    }}>
      <span style={{ fontWeight: 'bold' }}>{name}</span>
      {': '}raw={fmtNum(sig?.raw)}{' '}
      <span style={{ color: '#808080' }}>z={fmtNum(sig?.z_score, 2)}</span>
      {fired && <span style={{ color: '#008000', fontWeight: 'bold' }}> FIRED</span>}
    </div>
  )
}

function ExpandedPromotionRow({ promotion }) {
  const signals = Object.entries(promotion.signals || {})
  return (
    <tr style={{ background: '#e8e8ff' }}>
      <td colSpan={7} style={{ padding: '6px 8px', border: '1px solid #c0c0c0', borderTop: '1px solid #000080' }}>
        {signals.length > 0 ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 2, marginBottom: 6 }}>
            {signals.map(([name, sig]) => <SignalChip key={name} name={name} sig={sig} />)}
          </div>
        ) : (
          <div style={{ ...MUTED, marginBottom: 6 }}>No signal detail recorded for this promotion.</div>
        )}
        <div style={{ fontFamily: MONO, fontSize: 11, lineHeight: 1.5, whiteSpace: 'normal' }}>
          <span style={{ fontWeight: 'bold' }}>Tier 2b reasoning (Llama 3.3):</span>{' '}
          {promotion.reasoning || <span style={{ color: '#808080' }}>No reasoning recorded for this promotion.</span>}
        </div>
      </td>
    </tr>
  )
}

function PromotionsTable({ promotions }) {
  const [expandedIdx, setExpandedIdx] = useState(null)

  if (promotions == null) return <div style={{ ...MUTED, padding: 6 }}>Loading…</div>
  if (promotions.length === 0) return <div style={{ ...MUTED, padding: 6 }}>{promotionsEmptyText()}</div>

  const shown = promotions.slice(0, 20)
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: MONO }}>
      <thead>
        <tr>
          <th style={TH}>#</th>
          <th style={TH}>SYMBOL</th>
          <th style={{ ...TH, textAlign: 'right' }}>SCORE</th>
          <th style={{ ...TH, textAlign: 'right' }}>FIRED</th>
          <th style={TH}>TOP SIGNALS</th>
          <th style={TH}>SLEEVE ROUTE</th>
          <th style={{ ...TH, textAlign: 'right' }}>AMP</th>
        </tr>
      </thead>
      <tbody>
        {shown.map((p, i) => {
          const expanded = expandedIdx === i
          return [
            <tr
              key={`row-${i}`}
              onClick={() => setExpandedIdx(expanded ? null : i)}
              style={{ background: expanded ? '#e8e8ff' : i % 2 ? '#f0f0f0' : '#fff', cursor: 'pointer' }}
            >
              <td style={TD}>{i + 1}</td>
              <td style={{ ...TD, fontWeight: 'bold' }}>{p.symbol}</td>
              <td style={{ ...TD, textAlign: 'right' }}>{fmtNum(p.composite_score, 4)}</td>
              <td style={{ ...TD, textAlign: 'right' }}>{p.signals_fired ?? '--'}</td>
              <td style={{ ...TD, fontSize: 10 }}>{(p.firing_rules || []).slice(0, 3).join(', ') || '--'}</td>
              <td style={TD}>{p.sleeve_id ? <SleeveBadge id={p.sleeve_id} /> : '--'}</td>
              <td style={{ ...TD, textAlign: 'right' }}>
                {p.amplification != null && p.amplification > 1 ? `${Number(p.amplification).toFixed(1)}x` : ''}
              </td>
            </tr>,
            expanded && <ExpandedPromotionRow key={`exp-${i}`} promotion={p} />,
          ]
        })}
      </tbody>
    </table>
  )
}

// ── right rail ───────────────────────────────────────────────

function FireRatesPanel({ signals }) {
  return (
    <Panel title="Signal Fire Rates (14d)" bodyPad="4px 6px">
      {signals == null && <div style={MUTED}>Loading…</div>}
      {signals != null && signals.length === 0 && (
        <div style={MUTED}>No Tier 2 observations in the last 14 days.</div>
      )}
      {(signals || []).map((s) => (
        <div key={s.signal} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '1px 0' }}>
          <span style={{
            width: 100, textAlign: 'right', fontFamily: UI, fontSize: 10,
            whiteSpace: 'nowrap', overflow: 'hidden', flexShrink: 0,
          }}>{s.signal}</span>
          <BarMeter pct={s.rate} height={12} />
          <span style={{ width: 36, textAlign: 'right', flexShrink: 0, fontFamily: MONO, fontSize: 11 }}>
            {Number(s.rate).toFixed(0)}%
          </span>
        </div>
      ))}
    </Panel>
  )
}

// Static production schedule: 08:00 T1 · 10:00/12:00/14:00 T2a (+2b at :10) · lead at :20.
const SCHEDULE = [
  { min: 480, label: '08:00 Tier 1 sweep', kind: 't1' },
  { min: 600, label: '10:00 Tier 2a · :10 2b', kind: 't2' },
  { min: 620, label: '10:20 Lead cycle', kind: 'lead' },
  { min: 720, label: '12:00 Tier 2a · :10 2b', kind: 't2' },
  { min: 740, label: '12:20 Lead cycle', kind: 'lead' },
  { min: 840, label: '14:00 Tier 2a · :10 2b', kind: 't2' },
  { min: 860, label: '14:20 Lead cycle', kind: 'lead' },
]

function SchedulePanel({ status, todayCycles }) {
  const lastRun = {
    t1: etMinutes(status?.last_tier1_sweep),
    t2: etMinutes(status?.last_tier2_sweep),
    lead: todayCycles == null || todayCycles.length === 0
      ? null
      : Math.max(...todayCycles.map((c) => etMinutes(c.timestamp) ?? -1)),
  }
  return (
    <Panel title="Scan Schedule" bodyPad="4px 6px" bodyStyle={{ fontFamily: MONO, fontSize: 11 }}>
      {SCHEDULE.map((row) => {
        const ref = lastRun[row.kind]
        const done = ref != null && ref >= row.min
        return (
          <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', padding: '1px 0' }}>
            <span>{row.label}</span>
            {done
              ? <span style={{ color: '#008000', fontWeight: 'bold' }}>{'✓'} DONE</span>
              : <span style={{ color: '#808080' }}>pending</span>}
          </div>
        )
      })}
      <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: '1px solid #808080', marginTop: 2, paddingTop: 3 }}>
        <span>Lead cycles today</span>
        <span style={{ fontWeight: 'bold' }}>{todayCycles == null ? '--' : `${todayCycles.length} of 3`}</span>
      </div>
    </Panel>
  )
}

// ── page ─────────────────────────────────────────────────────

export default function PipelinePage() {
  const [status, setStatus] = useState(null)
  const [promotions, setPromotions] = useState(null)
  const [promoCount, setPromoCount] = useState(null)
  const [signals, setSignals] = useState(null)
  const [todayCycles, setTodayCycles] = useState(null)

  useEffect(() => {
    fetchDashboardStatus().then(setStatus).catch(() => {})
    fetchDashboardPromotions()
      .then((d) => { setPromotions(d?.promotions || []); setPromoCount(d?.count ?? (d?.promotions || []).length) })
      .catch(() => { setPromotions([]); setPromoCount(0) })
    fetchDashboardSignals(14).then((d) => setSignals(d?.signals || [])).catch(() => setSignals([]))
    fetchDashboardCycles(10, 1).then((d) => setTodayCycles(d?.cycles || [])).catch(() => setTodayCycles([]))
  }, [])

  const funnel = status?.funnel
  const cycle0 = todayCycles?.[0]
  const t2Examined = funnel ? (funnel.tier2_promoted || 0) + (funnel.tier2_rejected || 0) : undefined

  const stages = [
    {
      label: 'Tier 1 Sweep', count: funnel?.tier1_universe, sub: 'symbols observed',
      detail: status?.last_tier1_sweep ? `swept ${fmtTimeET(status.last_tier1_sweep)}` : '--',
    },
    {
      label: 'Tier 2a Prefilter', count: t2Examined, sub: 'names examined',
      detail: status?.last_tier2_sweep ? `ran ${fmtTimeET(status.last_tier2_sweep)} · 3x daily` : '--',
    },
    {
      label: 'Tier 2b Promoted', count: funnel?.tier2_promoted,
      sub: funnel ? `${funnel.tier2_rejected} rejected` : '--',
      detail: status?.last_tier2_sweep ? `latest ${fmtTimeET(status.last_tier2_sweep)}` : '--',
    },
    {
      label: 'Lead Agent', count: cycle0?.actions_decided, sub: 'actions decided',
      detail: cycle0 ? `cycle ${fmtTimeET(cycle0.timestamp)} · $${(cycle0.llm_cost_usd || 0).toFixed(4)}` : '--',
      bg: '#e8e8ff', color: '#000080',
    },
    {
      label: 'Trades', count: cycle0?.actions_executed, sub: 'executed last cycle',
      detail: cycle0 ? `of ${cycle0.actions_decided ?? '--'} decided` : '--',
      bg: '#000080', color: '#fff', labelColor: '#a0a0ff',
    },
  ]

  const promoTitle = promoCount == null
    ? "Today's Promotions"
    : `Today's Promotions (${promoCount})${promoCount > 20 ? ' — top 20 by composite score' : ''}`

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      <SpineStrip
        expanded
        stages={stages}
        regime={cycle0 ? cycle0.regime : null}
        llmSpend={status?.today_llm_cost}
      />
      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 330px', gap: 4, padding: 4, minHeight: 0, alignItems: 'start' }}>
        <Panel title={promoTitle} right={<span style={{ color: '#a0a0ff' }}>CLICK ROW TO EXPAND</span>} bodyPad={0}>
          <PromotionsTable promotions={promotions} />
        </Panel>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minHeight: 0 }}>
          <FireRatesPanel signals={signals} />
          <SchedulePanel status={status} todayCycles={todayCycles} />
          <Panel title="Near Misses — 2a rejects worth watching" bodyPad="4px 6px">
            <div style={{ ...MUTED, lineHeight: 1.5 }}>
              Near-miss feed needs a promotions?include=near_miss API — not yet exposed
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}
