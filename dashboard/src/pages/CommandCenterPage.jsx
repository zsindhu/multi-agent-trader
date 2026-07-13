/**
 * Command Center — final design 5a (Win95 × Bloomberg redesign).
 *
 * Pipeline spine strip → body grid 1fr/300px:
 *   left:  equity chart + sleeve P&L, 4 sleeve cards, active positions table
 *   right: live agent activity terminal, 3-state learning progress, integrity
 *
 * All data is real API data — panels show '--' / honest empty states when an
 * endpoint has nothing.
 */
import { useState, useEffect, useCallback, useMemo } from 'react'
import { Link } from 'react-router-dom'
import Panel from '../components/Panel'
import SpineStrip from '../components/SpineStrip'
import {
  SegmentedProgress, ProgressLegend, TerminalFeed, BarMeter, activityKind,
} from '../components/bits'
import { SLEEVES, sleeveInfo, fmtMoney, pnlColor, fmtTimeET, MONO, UI } from '../lib/design'
import {
  fetchDashboardStatus,
  fetchOptions,
  fetchDashboardTrades,
  fetchReconciliation,
  fetchConflicts,
  fetchActivity,
  fetchFillQuality,
  fetchDashboardDailyStats,
  fetchDashboardCycles,
} from '../api'

// ── Helpers ──────────────────────────────────────────────────

function dteFromExp(exp) {
  if (!exp) return '--'
  const diff = Math.floor((new Date(exp) - new Date()) / 86400000)
  return diff >= 0 ? diff : 0
}

function fmtExp(exp) {
  if (!exp) return '--'
  const s = String(exp).slice(0, 10) // YYYY-MM-DD
  const [, m, d] = s.split('-')
  return m && d ? `${Number(m)}/${Number(d)}` : s
}

function shortAgent(name) {
  return (name || 'sys').replace(/[-_ ]?(agent|analyst)$/i, '').slice(0, 14).toUpperCase()
}

// ── Equity chart (SVG line, navy on #e8e8ff area) ────────────

function EquityChart({ points }) {
  if (!points || points.length < 2) {
    return (
      <div style={{ fontFamily: UI, fontSize: 10, color: '#808080', padding: 6 }}>
        Not enough equity history to chart.
      </div>
    )
  }
  const vals = points.map((p) => p.equity)
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const span = max - min || 1
  const W = 1000
  const H = 300
  const pad = 14
  const xy = points.map((p, i) => [
    (i / (points.length - 1)) * W,
    H - pad - ((p.equity - min) / span) * (H - pad * 2),
  ])
  const line = xy.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')
  return (
    <div style={{ position: 'absolute', inset: 4 }}>
      <svg width="100%" height="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ display: 'block' }}>
        <polygon points={`0,${H} ${line} ${W},${H}`} fill="#e8e8ff" />
        <polyline points={line} fill="none" stroke="#000080" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      </svg>
      <div style={{ position: 'absolute', top: 0, left: 2, fontFamily: MONO, fontSize: 9, color: '#808080' }}>
        {fmtMoney(max)}
      </div>
      <div style={{ position: 'absolute', bottom: 0, left: 2, fontFamily: MONO, fontSize: 9, color: '#808080' }}>
        {fmtMoney(min)}
      </div>
    </div>
  )
}

// ── Integrity panel bits ─────────────────────────────────────

function IRow({ label, children }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '1px 0', gap: 6 }}>
      <span style={{ fontFamily: UI, fontSize: 10, color: '#808080', whiteSpace: 'nowrap' }}>{label}</span>
      <span style={{ textAlign: 'right' }}>{children}</span>
    </div>
  )
}

function ISection({ children, first = false }) {
  return (
    <div
      style={{
        fontFamily: UI, fontSize: 9, color: '#808080', textTransform: 'uppercase', letterSpacing: '0.5px',
        ...(first ? { marginBottom: 2 } : { margin: '6px 0 2px', borderTop: '1px solid #d0d0d0', paddingTop: 4 }),
      }}
    >
      {children}
    </div>
  )
}

function ModeBadge({ mode }) {
  const m = (mode || 'FALLBACK').toUpperCase()
  const bg = m === 'LLM_JUDGED' ? '#e8e8ff' : '#f0f0f0'
  return (
    <span style={{ fontFamily: UI, fontSize: 9, padding: '0 4px', border: '1px solid #808080', background: bg }}>
      {m}
    </span>
  )
}

// ── Table cell styles ────────────────────────────────────────

const TH = {
  background: '#000080', color: '#fff', fontFamily: UI, fontSize: 11,
  padding: '2px 6px', textAlign: 'left', border: '1px solid #808080', fontWeight: 'bold',
}
const THR = { ...TH, textAlign: 'right' }
const TD = { padding: '2px 6px', border: '1px solid #c0c0c0' }
const TDR = { ...TD, textAlign: 'right' }

// ── Main page ────────────────────────────────────────────────

export default function CommandCenterPage() {
  const [status, setStatus] = useState(null)
  const [cycle, setCycle] = useState(null)          // latest Lead Agent cycle
  const [tradesData, setTradesData] = useState(null) // 365d trades + summary
  const [tradesToday, setTradesToday] = useState(null) // count of today's entry orders
  const [options, setOptions] = useState(null)
  const [recon, setRecon] = useState(null)
  const [conflicts, setConflicts] = useState(null)
  const [activity, setActivity] = useState(null)
  const [fillQuality, setFillQuality] = useState(null)
  const [daily, setDaily] = useState(null)

  const loadActivity = useCallback(() => {
    fetchActivity(40).then((d) => setActivity(d?.events || [])).catch(() => {})
  }, [])

  const loadAll = useCallback(() => {
    fetchDashboardStatus().then(setStatus).catch(() => {})
    fetchDashboardCycles(1).then((d) => setCycle(d?.cycles?.[0] || null)).catch(() => {})
    fetchDashboardTrades(365).then(setTradesData).catch(() => {})
    fetchDashboardTrades(1)
      .then((d) => setTradesToday((d?.trades || []).filter((t) => t.trade_type === 'sell_to_open').length))
      .catch(() => {})
    fetchOptions().then((d) => setOptions(d?.options || [])).catch(() => setOptions([]))
    fetchReconciliation().then((d) => setRecon(d?.report || null)).catch(() => {})
    fetchConflicts(7).then((d) => setConflicts(d?.conflicts || [])).catch(() => setConflicts([]))
    fetchFillQuality(30).then(setFillQuality).catch(() => {})
    fetchDashboardDailyStats(30).then((d) => setDaily(d?.daily || [])).catch(() => {})
    loadActivity()
  }, [loadActivity])

  useEffect(() => {
    loadAll()
    const slow = setInterval(loadAll, 60000)
    const fast = setInterval(loadActivity, 15000)
    return () => { clearInterval(slow); clearInterval(fast) }
  }, [loadAll, loadActivity])

  // ── Derived data ───────────────────────────────────────────

  const funnel = status?.funnel
  const lp = status?.learning_progress

  const stages = useMemo(() => ([
    { label: 'Universe', count: funnel ? funnel.tier1_universe : null, sub: 'scanned' },
    { label: 'Tier 2A', count: funnel ? funnel.tier2_promoted + funnel.tier2_rejected : null, sub: 'evaluated' },
    { label: 'Tier 2B', count: funnel ? funnel.tier2_promoted : null, sub: 'promoted' },
    {
      label: 'Lead Agent',
      count: cycle ? cycle.actions_decided : null,
      sub: cycle?.timestamp ? `${fmtTimeET(cycle.timestamp)} cycle` : 'no cycle yet',
      bg: '#e8e8ff', color: '#000080', labelColor: '#000080',
    },
    {
      label: 'Trades',
      count: tradesToday,
      sub: 'entries today',
      bg: '#000080', color: '#fff', labelColor: '#a0a0ff',
    },
  ]), [funnel, cycle, tradesToday])

  const sweepNote = status?.last_tier2_sweep
    ? `as of ${fmtTimeET(status.last_tier2_sweep)} sweep`
    : null

  // Equity series from daily-stats (only days with an equity snapshot)
  const eqPoints = useMemo(
    () => (daily || []).filter((d) => d.equity != null),
    [daily],
  )
  const lastEq = eqPoints.length ? eqPoints[eqPoints.length - 1].equity : null
  const firstEq = eqPoints.length ? eqPoints[0].equity : null
  const eqPct = eqPoints.length >= 2 && firstEq ? ((lastEq - firstEq) / firstEq) * 100 : null
  const eqToday = eqPoints.length >= 2 ? lastEq - eqPoints[eqPoints.length - 2].equity : null
  const upDown = (n) => (n >= 0 ? '#80ff80' : '#ff8080')

  const equityTitle = (
    <span>
      Equity — {fmtMoney(lastEq)}
      {eqPct != null && (
        <span style={{ color: upDown(eqPct) }}> {eqPct >= 0 ? '+' : ''}{eqPct.toFixed(1)}%</span>
      )}
      {eqToday != null && (
        <> · today <span style={{ color: upDown(eqToday) }}>{fmtMoney(eqToday, { sign: true })}</span></>
      )}
    </span>
  )

  // Sleeve P&L (labeled outcomes, 365d)
  const bySleeve = tradesData?.summary?.by_sleeve || {}
  const sleeveIds = useMemo(() => {
    const ids = Object.keys(SLEEVES)
    for (const k of Object.keys(bySleeve)) if (!ids.includes(k)) ids.push(k)
    return ids
  }, [bySleeve])
  const maxAbsPnl = Math.max(1, ...Object.values(bySleeve).map((s) => Math.abs(s.pnl || 0)))

  // Premium MTD from filled entry trades this calendar month
  const premiumMTD = useMemo(() => {
    if (!tradesData) return null
    const now = new Date()
    const monthKey = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, '0')}`
    let sum = 0
    let any = false
    for (const t of tradesData.trades || []) {
      if (t.trade_type !== 'sell_to_open') continue
      if (!['filled', 'partially_filled', 'closed', 'assigned'].includes(t.status)) continue
      if (!t.created_at || !t.created_at.startsWith(monthKey)) continue
      const px = t.fill_price != null ? t.fill_price : t.premium
      if (px == null || t.quantity == null) continue
      sum += Number(px) * Number(t.quantity) * 100
      any = true
    }
    return any ? sum : 0
  }, [tradesData])

  // Open positions per sleeve, attributed via open entry trades
  const openBySleeve = useMemo(() => {
    const out = {}
    for (const t of tradesData?.trades || []) {
      if (t.display_outcome !== 'Open') continue
      const sid = t.trade_sleeve_id || 'unattributed'
      out[sid] = (out[sid] || 0) + 1
    }
    return out
  }, [tradesData])

  // Alpaca column per position
  const alpacaStatus = (o) => {
    if (!recon) return { text: '--', color: '#808080' }
    const mentioned = (recon.discrepancies || []).some((d) => {
      const ds = d.option_symbol || ''
      return ds && (ds === o.option_symbol || ds.startsWith(o.symbol))
    })
    if (recon.ok && !mentioned) return { text: 'MATCH', color: '#008000' }
    return { text: 'PENDING', color: '#808000' }
  }

  // Integrity header status
  const allPass = recon?.ok && status?.today_errors === 0
  let integrityRight = null
  if (recon && status) {
    const issues = (recon.ok ? 0 : Math.max(recon.discrepancy_count || 0, 1)) + (status.today_errors || 0)
    integrityRight = (
      <span style={{ color: allPass ? '#80ff80' : '#ffff00' }}>
        {allPass ? 'ALL CHECKS PASS' : `${issues} ISSUES`}
      </span>
    )
  }

  const feedRows = useMemo(() => (activity || []).map((e) => ({
    time: fmtTimeET(e.timestamp),
    agent: shortAgent(e.agent),
    text: `${e.action_type || ''}${e.symbol ? ' ' + e.symbol : ''}${e.reason ? ' — ' + e.reason : ''}`.slice(0, 140),
    kind: activityKind(e),
  })), [activity])

  const posItems = (options || []).filter((p) => !p.status || p.status === 'open' || p.quantity !== 0)
  const fq = fillQuality
  const lowFill = fq?.fill_rate_pct != null && fq.fill_rate_pct < 60
  const toGo = lp ? Math.max(0, (lp.threshold || 50) - (lp.clean || 0)) : null

  // ── Render ─────────────────────────────────────────────────

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, background: '#c0c0c0', fontFamily: UI }}>
      <SpineStrip
        stages={stages}
        sweepNote={sweepNote}
        regime={cycle ? cycle.regime : null}
        llmSpend={status ? status.today_llm_cost : null}
        expanded={false}
      />

      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 300px', gap: 4, padding: 4, minHeight: 0 }}>
        {/* ── Left column ─────────────────────────────────── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minHeight: 0 }}>
          {/* Row 1: equity chart + sleeve P&L */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: 4 }}>
            <Panel
              title={equityTitle}
              bodyStyle={{ height: 150, flex: '0 0 auto', padding: 4, position: 'relative', overflow: 'hidden' }}
            >
              <EquityChart points={eqPoints} />
            </Panel>

            <Panel title="Sleeves — P&L" bodyStyle={{ padding: '4px 6px', fontFamily: MONO, fontSize: 11 }}>
              {sleeveIds.map((sid) => {
                const s = bySleeve[sid]
                const pnl = s ? s.pnl : null
                return (
                  <div key={sid} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '2px 0' }}>
                    <span style={{ width: 86, fontFamily: UI, fontSize: 10, whiteSpace: 'nowrap', overflow: 'hidden' }}>
                      {sleeveInfo(sid).name}
                    </span>
                    <BarMeter
                      pct={pnl != null ? (Math.abs(pnl) / maxAbsPnl) * 100 : 0}
                      color={pnl >= 0 ? '#008000' : '#ff0000'}
                      height={10}
                    />
                    <span style={{ width: 56, textAlign: 'right', fontWeight: 'bold', color: pnlColor(pnl) }}>
                      {pnl != null ? fmtMoney(pnl, { sign: true }) : '--'}
                    </span>
                  </div>
                )
              })}
              {premiumMTD != null && (
                <div style={{ borderTop: '1px solid #808080', marginTop: 4, paddingTop: 3, display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ fontFamily: UI, fontSize: 10, color: '#808080' }}>Total premium MTD</span>
                  <span style={{ fontWeight: 'bold' }}>{fmtMoney(premiumMTD)}</span>
                </div>
              )}
            </Panel>
          </div>

          {/* Row 2: sleeve cards */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 4 }}>
            {Object.keys(SLEEVES).map((sid) => {
              const info = sleeveInfo(sid)
              const s = bySleeve[sid]
              const openN = tradesData ? (openBySleeve[sid] || 0) : null
              return (
                <Panel
                  key={sid}
                  title={<span style={{ fontSize: 11 }}>{info.name}</span>}
                  right={<span style={{ fontFamily: MONO, fontSize: 9, color: '#a0a0ff' }}>{info.tag}</span>}
                  bodyStyle={{ padding: '4px 6px', fontFamily: MONO, fontSize: 11 }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: '#808080', fontFamily: UI, fontSize: 10 }}>P&L</span>
                    <span style={{ fontWeight: 'bold', color: pnlColor(s ? s.pnl : null) }}>
                      {s ? fmtMoney(s.pnl, { sign: true }) : '--'}
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: '#808080', fontFamily: UI, fontSize: 10 }}>Positions</span>
                    <span>{openN != null ? `${openN} open` : '--'}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: '#808080', fontFamily: UI, fontSize: 10 }}>Capital used</span>
                    <span>--</span>
                  </div>
                  <BarMeter pct={0} color="#000080" height={8} />
                </Panel>
              )
            })}
          </div>

          {/* Row 3: active positions */}
          <Panel
            title={`Active Positions (${posItems.length})`}
            right={recon?.ran_at && <span style={{ color: '#80ff80' }}>SYNCED {fmtTimeET(recon.ran_at)}</span>}
            style={{ flex: 1, minHeight: 0 }}
            bodyPad={0}
          >
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: MONO }}>
              <thead>
                <tr>
                  <th style={TH}>SYMBOL</th>
                  <th style={TH}>TYPE</th>
                  <th style={THR}>STRIKE</th>
                  <th style={THR}>EXP</th>
                  <th style={THR}>DTE</th>
                  <th style={THR}>ENTRY</th>
                  <th style={THR}>P&L</th>
                  <th style={TH}>ALPACA</th>
                </tr>
              </thead>
              <tbody>
                {options == null && (
                  <tr><td colSpan={8} style={{ ...TD, fontFamily: UI, fontSize: 10, color: '#808080' }}>Loading positions...</td></tr>
                )}
                {options != null && posItems.length === 0 && (
                  <tr><td colSpan={8} style={{ ...TD, fontFamily: UI, fontSize: 10, color: '#808080' }}>No open option positions.</td></tr>
                )}
                {posItems.map((p, i) => {
                  const a = alpacaStatus(p)
                  return (
                    <tr key={p.option_symbol || i} style={{ background: i % 2 ? '#f0f0f0' : '#fff' }}>
                      <td style={{ ...TD, fontWeight: 'bold' }}>{p.symbol}</td>
                      <td style={TD}>
                        {p.contract_type ? `${p.is_short ? 'SHORT ' : 'LONG '}${String(p.contract_type).toUpperCase()}` : '--'}
                      </td>
                      <td style={TDR}>{p.strike != null ? Number(p.strike).toFixed(2) : '--'}</td>
                      <td style={TDR}>{fmtExp(p.expiration)}</td>
                      <td style={TDR}>{dteFromExp(p.expiration)}</td>
                      <td style={TDR}>{p.entry_price != null ? `$${Number(p.entry_price).toFixed(2)}` : '--'}</td>
                      <td style={{ ...TDR, fontWeight: 'bold', color: pnlColor(p.pnl) }}>
                        {p.pnl != null ? fmtMoney(p.pnl, { sign: true }) : '--'}
                      </td>
                      <td style={{ ...TD, color: a.color }}>{a.text}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </Panel>
        </div>

        {/* ── Right rail ───────────────────────────────────── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minHeight: 0 }}>
          <Panel title="Agent Activity — Live" style={{ flex: 1, minHeight: 0 }} bodyPad={0} bodyBg="#000">
            <TerminalFeed rows={feedRows} emptyText={activity == null ? 'Connecting...' : 'No agent activity yet.'} />
          </Panel>

          <Panel title="Learning Progress" style={{ flexShrink: 0 }} bodyStyle={{ padding: 6, fontFamily: MONO, fontSize: 11 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
              <span style={{ fontFamily: UI, color: '#808080', fontSize: 10 }}>Clean decisions</span>
              <span style={{ fontWeight: 'bold' }}>{lp ? `${lp.clean} / ${lp.threshold}` : '--'}</span>
            </div>
            <SegmentedProgress clean={lp?.clean || 0} unknown={lp?.unknown || 0} total={lp?.threshold || 50} />
            <ProgressLegend clean={lp?.clean ?? '--'} unknown={lp?.unknown ?? '--'} />
            <div style={{ fontFamily: UI, fontSize: 10, color: '#404040', marginTop: 5, borderTop: '1px solid #d0d0d0', paddingTop: 4, lineHeight: 1.5 }}>
              <b>Jul 12 relabel:</b> {lp?.contaminated_excluded ?? '--'} pre-cutover labels excluded
              (decisions, not contracts; contaminated evidence removed). The learner trains only on
              clean decisions — this is the count that matters.
            </div>
            <div style={{ fontFamily: UI, fontSize: 10, color: '#808080', marginTop: 3 }}>
              Signal-weight learning activates at {lp?.threshold ?? 50}.{toGo != null ? ` ${toGo} to go.` : ''}
            </div>
          </Panel>

          <Panel
            title="Integrity"
            right={integrityRight}
            style={{ flexShrink: 0 }}
            bodyStyle={{ padding: '4px 6px', fontFamily: MONO, fontSize: 11 }}
          >
            <ISection first>Broker reconciliation</ISection>
            <IRow label="Orders">
              {recon ? (
                <span style={{ color: recon.ok ? '#008000' : '#808000', fontWeight: 'bold' }}>
                  {Math.max(0, (recon.orders_checked || 0) - (recon.discrepancy_count || 0))}/{recon.orders_checked || 0} matched
                  {recon.ran_at ? ` · ${fmtTimeET(recon.ran_at)}` : ''}
                </span>
              ) : '--'}
            </IRow>
            <IRow label="P&L drift">
              {recon?.pnl_drift != null
                ? <span style={{ color: '#808000', fontWeight: 'bold' }}>{fmtMoney(recon.pnl_drift)}</span>
                : '--'}
            </IRow>

            <ISection>Fill quality (30d)</ISection>
            <IRow label="Entry fill rate">
              {fq?.fill_rate_pct != null ? (
                <span style={{ color: lowFill ? '#808000' : '#008000', fontWeight: 'bold' }}>
                  {fq.fill_rate_pct}% ({fq.filled}/{fq.entry_orders})
                </span>
              ) : '--'}
            </IRow>
            <IRow label="Avg slippage">
              {fq?.avg_slippage != null
                ? `${fq.avg_slippage < 0 ? '-' : '+'}$${Math.abs(fq.avg_slippage).toFixed(2)} / contract`
                : '--'}
            </IRow>
            {lowFill && (
              <div style={{ fontFamily: UI, fontSize: 9, color: '#606060', padding: '1px 0' }}>
                {'⚠'} {Math.round(100 - fq.fill_rate_pct)}% of entries never fill — biggest drag on the n={lp?.threshold ?? 50} timeline
              </div>
            )}

            <ISection>Sleeve conflicts (7d)</ISection>
            {conflicts == null && <div style={{ fontFamily: UI, fontSize: 10, color: '#808080' }}>--</div>}
            {conflicts != null && conflicts.length === 0 && (
              <div style={{ fontFamily: UI, fontSize: 10, color: '#808080', padding: '1px 0' }}>None in last 7 days.</div>
            )}
            {(conflicts || []).slice(0, 2).map((c, i) => (
              <div key={i} style={{ padding: '1px 0', fontSize: 10 }}>
                <span style={{ fontWeight: 'bold' }}>{c.symbol || '--'}</span>
                {' — '}
                {sleeveInfo(c.winner).name.toLowerCase()} beat{' '}
                {(c.losers || []).length
                  ? c.losers.map((l) => sleeveInfo(l).name.toLowerCase()).join(', ')
                  : 'competing sleeves'}{' '}
                <ModeBadge mode={c.resolution_mode} />
              </div>
            ))}

            <ISection>System</ISection>
            <IRow label="Errors today">
              <span style={{ color: status?.today_errors > 0 ? '#ff0000' : undefined, fontWeight: status?.today_errors > 0 ? 'bold' : undefined }}>
                {status ? status.today_errors : '--'}
              </span>
            </IRow>
            <IRow label="Last cycle">
              {status?.last_cycle?.timestamp
                ? `${fmtTimeET(status.last_cycle.timestamp)}${status.last_cycle.cost != null ? ` ($${Number(status.last_cycle.cost).toFixed(4)})` : ''}`
                : '--'}
            </IRow>

            <div style={{ marginTop: 5, borderTop: '1px solid #d0d0d0', paddingTop: 4 }}>
              <Link to="/agents" style={{ fontFamily: UI, fontSize: 10, color: '#000080', textDecoration: 'none' }}>
                {'▶'} Full audit on Agents screen
              </Link>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}
