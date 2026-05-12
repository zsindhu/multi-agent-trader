import { useState, useEffect } from 'react'
import '../win95.css'
import W95Window from '../components/W95Window'
import { fetchDashboardSignals } from '../api'

// ── Expandable Section ───────────────────────────────────────

function Expandable({ title, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div style={{ borderBottom: '1px solid #808080' }}>
      <div
        onClick={() => setOpen(!open)}
        style={{
          padding: '3px 6px',
          cursor: 'pointer',
          background: open ? '#e8e8ff' : '#f0f0f0',
          fontFamily: 'var(--w95-font-ui)',
          fontSize: 12,
          fontWeight: 'bold',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          userSelect: 'none',
        }}
      >
        <span style={{ fontFamily: 'var(--w95-font-mono)', fontSize: 10, width: 12 }}>
          {open ? '\u25be' : '\u25b8'}
        </span>
        {title}
      </div>
      {open && (
        <div style={{
          padding: '6px 8px 8px 24px',
          background: '#ffffff',
          fontSize: 11,
          lineHeight: 1.6,
          fontFamily: 'var(--w95-font-ui)',
        }}>
          {children}
        </div>
      )}
    </div>
  )
}

function Label({ children }) {
  return (
    <span style={{
      fontFamily: 'var(--w95-font-ui)',
      fontWeight: 'bold',
      fontSize: 10,
      textTransform: 'uppercase',
      color: '#000080',
      letterSpacing: '0.5px',
    }}>
      {children}
    </span>
  )
}

function Mono({ children }) {
  return <span style={{ fontFamily: 'var(--w95-font-mono)', fontSize: 11 }}>{children}</span>
}

// ── Funnel Visualization ─────────────────────────────────────

function FunnelPanel() {
  const stages = [
    { label: 'Universe', count: '~6,350', desc: 'All active US equities with options (Alpaca asset discovery)' },
    { label: 'Tier 1', count: '~4,285', desc: 'Daily Breadth Analyst sweep — price $5-$10K, volume > 100K, market cap > $500M' },
    { label: 'Tier 2a', count: '~50-150', desc: 'Mechanical pre-filter — 11 rules scored, 2-rule minimum gate, $10M liquidity floor' },
    { label: 'Tier 2b', count: '~30-80', desc: 'LLM reasoning (Llama 3.3) — AI analyst explains why the signal combination matters' },
    { label: 'Lead Agent', count: '~5-15', desc: 'Claude evaluates top names against regime, positions, playbook, fundamentals' },
    { label: 'Trades', count: '0-3/day', desc: 'Orders submitted to Alpaca paper trading (CSPs, CCs, Wheel)' },
  ]

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 0, marginBottom: 8, flexWrap: 'wrap' }}>
        {stages.map((s, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{
              border: '2px outset #dfdfdf',
              background: i === 0 ? '#d4d0c8' : i === stages.length - 1 ? '#e8ffe8' : '#fff',
              padding: '4px 10px',
              textAlign: 'center',
              minWidth: 80,
            }}>
              <div style={{ fontFamily: 'var(--w95-font-mono)', fontWeight: 'bold', fontSize: 13 }}>{s.count}</div>
              <div style={{ fontSize: 9, color: '#808080', fontFamily: 'var(--w95-font-ui)' }}>{s.label}</div>
            </div>
            {i < stages.length - 1 && (
              <span style={{ fontSize: 14, color: '#000080', padding: '0 2px', fontWeight: 'bold' }}>{'\u2192'}</span>
            )}
          </div>
        ))}
      </div>

      {stages.map((s, i) => (
        <div key={i} style={{ fontSize: 11, marginBottom: 2 }}>
          <span className="w95-bold">{s.label}:</span>{' '}
          <span className="w95-muted">{s.desc}</span>
        </div>
      ))}
    </div>
  )
}

// ── Daily Schedule ───────────────────────────────────────────

const SCHEDULE = [
  { time: '6:00 AM', job: 'Earnings Refresh', desc: 'Finnhub bulk earnings calendar — fetches upcoming earnings for the full universe. Updates the earnings_event table so Rule 8 and the Lead Agent have fresh data.', llm: false, cost: null, group: 'pre' },
  { time: '7:30 AM', job: 'Pre-Market Briefing', desc: 'Assembles yesterday\'s Research Analyst reflection + active playbook entries into a briefing document. No LLM — pure template assembly. The Lead Agent reads this as its first tool call each cycle.', llm: false, cost: null, group: 'pre' },
  { time: '8:00 AM', job: 'Breadth Analyst (Tier 1)', desc: 'Sweeps ~6,350 optionable US equities through mechanical filters: price $5-$10K, volume > 100K, market cap > $500M. Produces ~4,285 names that enter the Tier 2 pipeline. Results stored in name_observations (tier=1).', llm: false, cost: null, group: 'pre' },
  { time: '9:00 AM', job: 'News Refresh', desc: 'Finnhub macro news headlines — broad market news for the Lead Agent\'s context. Not symbol-specific; symbol news is fetched on-demand during Tier 2a for the top 200 names.', llm: false, cost: null, group: 'pre' },
  { time: '9:35 AM', job: 'Regime Refresh', desc: 'Computes market regime from VIX level, SPY trend (20MA/50MA), market breadth (% above 20MA), sector rotation, and credit stress. Determines risk-on/risk-off/neutral classification that guides all trade decisions.', llm: false, cost: null, group: 'pre' },

  { time: '10:00 AM', job: 'Tier 2a Pre-Filter', desc: 'Scores all ~4,285 Tier 1 names against 11 mechanical rules. Fetches on-demand data for top names: news (top 200), yfinance options (top 100), StockTwits (top 50). Produces ~525 promoted names with composite scores. Runtime: ~3 minutes.', llm: false, cost: null, group: 'cycle1' },
  { time: '10:10 AM', job: 'Tier 2b Reasoning', desc: 'Llama 3.3 70B (Together AI) reads each promoted name\'s signal profile and writes a narrative explanation of why the signal combination matters. 25 names per batch. Stored in analysis.tier2b_reasoning.', llm: true, cost: '$0.93', group: 'cycle1' },
  { time: '10:20 AM', job: 'Lead Agent Cycle', desc: '4 parallel Claude calls (one per sleeve: vol_reversion, event_driven, yield_farming, sector_rotation). Each sees its filtered candidates from Tier 2, reads briefing/playbook/regime, makes trade decisions. Conflict resolution via Llama 3.3 if two sleeves want the same name. SleeveRiskGate checks every action.', llm: true, cost: '$2-3', group: 'cycle1' },

  { time: '12:00 PM', job: 'News Refresh + Tier 2a', desc: 'Re-scores the universe with fresh intraday data. Names that spiked mid-morning get picked up here. Same 11-rule pipeline as 10:00 AM.', llm: false, cost: null, group: 'cycle2' },
  { time: '12:10 PM', job: 'Tier 2b Reasoning', desc: 'Re-reasons on the updated promotion list. Names that were promoted at 10:00 AM but not at 12:00 PM drop off; new ones appear.', llm: true, cost: '$0.93', group: 'cycle2' },
  { time: '12:20 PM', job: 'Lead Agent Cycle', desc: 'Second daily sleeve cycle. Positions opened at 10:20 AM are now 2 hours old — the Lead Agent manages them (hold/close/roll) alongside evaluating new candidates.', llm: true, cost: '$2-3', group: 'cycle2' },
  { time: '12:30 PM', job: 'Regime Refresh', desc: 'Mid-day regime re-computation. Catches intraday VIX spikes or breadth collapses that should change the risk posture.', llm: false, cost: null, group: 'cycle2' },

  { time: '2:00 PM', job: 'Tier 2a Pre-Filter', desc: 'Final scoring run. Captures afternoon movers. Last chance for new names to enter the funnel before market close.', llm: false, cost: null, group: 'cycle3' },
  { time: '2:10 PM', job: 'Tier 2b Reasoning', desc: 'Final reasoning run. Llama 3.3 reasons on afternoon promotion list.', llm: true, cost: '$0.93', group: 'cycle3' },
  { time: '2:20 PM', job: 'Lead Agent Cycle', desc: 'Final daily sleeve cycle. Focus shifts toward position management: any position with < 5 DTE or > 50% profit target gets evaluated for close/roll. New positions rare this late unless a strong setup appeared in the afternoon Tier 2a run.', llm: true, cost: '$2-3', group: 'cycle3' },

  { time: '4:05 PM', job: 'Daily Summary', desc: 'Discord notification with today\'s trade activity, P&L, and position changes. No LLM — template-based.', llm: false, cost: null, group: 'post' },
  { time: '4:30 PM', job: 'Performance Analytics', desc: 'Computes daily stats: win rate by delta bucket, regime correlation, per-symbol track record, strategy breakdown. Stored for the Research Analyst to read tomorrow.', llm: false, cost: null, group: 'post' },
  { time: '5:00 PM', job: 'Outcome Labeler', desc: 'Labels completed trades with PnL, holding period, underlying return, and signal profile at entry. Links trades to the name_observations that surfaced them (funnel attribution). This is the ground truth for the signal-weight learner.', llm: false, cost: null, group: 'post' },
  { time: '5:30 PM', job: 'Research Analyst', desc: 'Daily reflection: reads today\'s cycle snapshots, top promotions, trade outcomes, and writes a narrative about what patterns emerged. Tomorrow\'s Lead Agent reads this reflection in its pre-market briefing. This is how the system learns across days.', llm: true, cost: '$0.05', group: 'post' },
]

const GROUP_LABELS = {
  pre: { label: 'Pre-Market', color: '#808000' },
  cycle1: { label: 'Cycle 1 — Morning', color: '#000080' },
  cycle2: { label: 'Cycle 2 — Midday', color: '#000080' },
  cycle3: { label: 'Cycle 3 — Afternoon', color: '#000080' },
  post: { label: 'Post-Market', color: '#800000' },
}

function SchedulePanel() {
  const [openGroups, setOpenGroups] = useState({ pre: false, cycle1: true, cycle2: false, cycle3: false, post: false })

  const toggle = (g) => setOpenGroups(prev => ({ ...prev, [g]: !prev[g] }))

  const groups = ['pre', 'cycle1', 'cycle2', 'cycle3', 'post']

  return (
    <div>
      <div style={{ fontSize: 11, marginBottom: 6, fontFamily: 'var(--w95-font-ui)', lineHeight: 1.6 }}>
        The system runs <strong>3 scoring cycles per day</strong> during market hours (10:00, 12:00, 2:00 PM ET).
        Each cycle follows the same pipeline: Tier 2a scores {'\u2192'} Tier 2b reasons {'\u2192'} Lead Agent decides.
        Data feeds and the learning loop run before and after market hours.
      </div>

      <div style={{ fontSize: 11, marginBottom: 8, padding: '3px 6px', background: '#f0f0f0', border: '1px solid #c0c0c0' }}>
        <strong>Daily estimated cost:</strong>{' '}
        <span style={{ fontFamily: 'var(--w95-font-mono)' }}>
          3 \u00d7 ($0.93 Tier2b + $2.50 Lead) + $0.05 Research = <strong>~$10.34/day</strong> (~$218/month)
        </span>
        <span className="w95-muted"> · With prompt caching: ~$6/day (~$131/month)</span>
      </div>

      {groups.map(g => {
        const groupInfo = GROUP_LABELS[g]
        const jobs = SCHEDULE.filter(s => s.group === g)
        const groupCost = jobs.filter(j => j.cost).map(j => j.cost).join(' + ') || 'Free'
        const isOpen = openGroups[g]

        return (
          <div key={g} style={{ marginBottom: 2 }}>
            <div
              onClick={() => toggle(g)}
              style={{
                padding: '3px 6px', cursor: 'pointer', userSelect: 'none',
                background: isOpen ? '#e8e8ff' : '#f0f0f0',
                borderBottom: '1px solid #808080',
                display: 'flex', alignItems: 'center', gap: 6,
                fontFamily: 'var(--w95-font-ui)', fontSize: 12, fontWeight: 'bold',
              }}
            >
              <span style={{ fontFamily: 'var(--w95-font-mono)', fontSize: 10, width: 12 }}>
                {isOpen ? '\u25be' : '\u25b8'}
              </span>
              <span style={{ color: groupInfo.color }}>{groupInfo.label}</span>
              <span style={{ fontWeight: 'normal', color: '#808080', fontSize: 10, marginLeft: 'auto' }}>
                {jobs.length} jobs · {groupCost}
              </span>
            </div>
            {isOpen && (
              <table className="w95-table" style={{ marginBottom: 0 }}>
                <thead>
                  <tr><th style={{ width: 75 }}>Time</th><th style={{ width: 160 }}>Job</th><th>Description</th><th style={{ width: 35 }}>LLM</th><th style={{ width: 50 }}>Cost</th></tr>
                </thead>
                <tbody>
                  {jobs.map((s, i) => (
                    <tr key={i}>
                      <td style={{ fontFamily: 'var(--w95-font-mono)', fontWeight: 'bold' }}>{s.time}</td>
                      <td className="w95-bold">{s.job}</td>
                      <td style={{ whiteSpace: 'normal', fontSize: 10, lineHeight: 1.5 }}>{s.desc}</td>
                      <td style={{ textAlign: 'center' }}>{s.llm ? <span style={{ color: '#000080', fontWeight: 'bold' }}>Yes</span> : <span className="w95-muted">No</span>}</td>
                      <td style={{ fontFamily: 'var(--w95-font-mono)', textAlign: 'right' }}>{s.cost || '\u2014'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )
      })}

      <div style={{ fontSize: 10, color: '#808080', marginTop: 6, fontFamily: 'var(--w95-font-ui)' }}>
        All times Eastern. The Lead Agent only runs during market hours (9:30 AM – 4:00 PM ET, weekdays).
        Container restarts outside market hours skip the startup cycle to avoid wasted LLM spend.
      </div>
    </div>
  )
}

// ── Rule Data ────────────────────────────────────────────────

const RULES = [
  {
    num: 1,
    name: 'Volume Z-Score',
    signal: 'volume_zscore',
    weight: 0.20,
    threshold: 'Robust z \u2265 2.0',
    what: "Measures whether today's trading volume is abnormally high compared to the stock's own 60-day history.",
    math: `For each name, we take the last 60 days of daily volume. Instead of the mean (which one giant day can inflate), we use the median — the middle value. For spread, we use Median Absolute Deviation (MAD) instead of standard deviation.

robust_z = (today_volume - median_60d) / (MAD_60d \u00d7 1.4826)

The 1.4826 factor makes MAD comparable to standard deviation for normal distributions. If MAD is zero (thinly traded name with identical volumes), we fall back to mean/stdev.`,
    whyThreshold: `A z-score of 2.0 means today's volume is roughly 2 standard deviations above the name's own baseline. For normally distributed data this would be the top ~2.5%. Real volume data is fat-tailed, so it fires somewhat more often — typically 15-25% of evaluated names, which is selective enough to be meaningful.`,
    tradingMeaning: `Abnormal volume often precedes or accompanies significant price moves. For premium sellers, it can signal: institutional activity (block trades), unusual options hedging flowing into shares, or news-driven interest the market hasn't fully priced yet. Combined with other signals, it identifies names entering an "active phase."`,
    dataSource: 'historical_bars table (Stooq / yfinance / Alpaca)',
  },
  {
    num: 2,
    name: 'Range Expansion',
    signal: 'range_expansion',
    weight: 0.15,
    threshold: 'Range / ATR \u2265 1.5',
    what: "Compares today's high-low range to the name's own 20-day Average True Range (ATR).",
    math: `True Range for each day = max(High - Low, |High - PrevClose|, |Low - PrevClose|)

We compute the median of these true ranges over 20 days (robust ATR). Then:

expansion_ratio = today's range / median_ATR_20d

Using median instead of mean prevents a single gap day from inflating the ATR baseline.`,
    whyThreshold: `1.5\u00d7 catches genuine breakouts while filtering normal variation. At 1.0\u00d7, you'd fire about half the time (useless). At 2.0\u00d7, you miss many real moves. 1.5\u00d7 fires roughly 30-35% of the time — selective enough to flag genuine regime changes in a name's volatility.`,
    tradingMeaning: `A name whose range suddenly exceeds its own baseline is entering a new volatility regime. For premium sellers, this usually means higher implied volatility (more premium to collect) but also more risk of the underlying moving through your strike. It's the classic risk/reward signal for options.`,
    dataSource: 'historical_bars table',
  },
  {
    num: 3,
    name: 'Gap Z-Score',
    signal: 'gap_zscore',
    weight: 0.15,
    threshold: '|Robust z| \u2265 2.0',
    what: "Measures the overnight gap (today's open vs yesterday's close) relative to the name's 60-day gap distribution.",
    math: `gap_pct = (today_open - yesterday_close) / yesterday_close

We compute median and MAD of the last 60 daily gap percentages, then:

robust_z = |gap_pct - median_gaps| / (MAD_gaps \u00d7 1.4826)

We use absolute value because both large up-gaps and down-gaps are interesting for premium sellers.`,
    whyThreshold: `Same logic as Rule 1: z \u2265 2.0 flags statistically unusual gaps. Robust statistics prevent a single earnings gap from contaminating the baseline for weeks. The per-name normalization means a 2% gap on TSLA (which regularly gaps 3-4%) won't fire, but a 2% gap on KO (which rarely gaps 0.5%) will.`,
    tradingMeaning: `Large overnight gaps indicate news, analyst actions, or institutional repositioning. The gap itself may have already moved the stock, but the implied volatility response often lingers for days — creating premium selling opportunities if you believe the move is overdone.`,
    dataSource: 'historical_bars table',
  },
  {
    num: 4,
    name: 'IV Rank Delta',
    signal: 'iv_rank_delta',
    weight: 0.20,
    threshold: '|Robust z| \u2265 2.0 (per-name)',
    what: "Measures the 5-day change in implied volatility rank, normalized against each name's own historical delta distribution.",
    math: `IV Rank = where current realized vol sits in its 252-day range (0-100).
Realized vol at each point = 20-day rolling log-return standard deviation, annualized (\u00d7 \u221a252 \u00d7 100).

iv_rank = (current_vol - min_252d) / (max_252d - min_252d) \u00d7 100
delta = iv_rank_today - iv_rank_5_days_ago

Then for names with 20+ historical deltas, we compute:
robust_z = |delta - median_of_all_historical_deltas| / (MAD_of_deltas \u00d7 1.4826)

For names without enough history, fallback: |delta| \u2265 15 points.`,
    whyThreshold: `The old fixed 15-point threshold fired at 81.7% (!) because high-vol names like TSLA routinely swing 15+ IV rank points. Per-name normalization via robust z-score corrects this: a 15-point swing on TSLA might only be z=0.8 (normal for TSLA), while the same swing on JNJ is z=3.5 (extremely unusual for JNJ).`,
    tradingMeaning: `This is the core premium selling signal. A sudden IV rank spike means options are getting more expensive relative to the name's own history. If you believe the spike will revert (no fundamental catalyst), selling premium captures the mean reversion. This is why it has the highest weight (0.20).`,
    dataSource: 'historical_bars table (realized vol proxy)',
  },
  {
    num: 5,
    name: 'Put/Call Volume Ratio',
    signal: 'put_call_ratio',
    weight: 0.10,
    threshold: 'Ratio > 1.5 or < 0.5',
    what: "Measures the ratio of put volume to call volume across the nearest-expiration options chain.",
    math: `ratio = total_put_volume / total_call_volume (nearest expiration)

If total_call_volume = 0 but puts exist: ratio = 999.0, score = 1.0
Fires if ratio > 1.5 (heavy put buying) or ratio < 0.5 (heavy call buying).
distance = |ratio - 1.0|
score = min(1.0, distance / 1.0)`,
    whyThreshold: `A neutral market has roughly equal put and call activity (ratio near 1.0). Above 1.5 means put buyers outnumber call buyers 3:2 — institutional hedging or directional bets. Below 0.5 means call speculation dominates. Both extremes indicate positioning that can drive future volatility.`,
    tradingMeaning: `Extreme put/call ratios signal that the options market is pricing in a directional move. For premium sellers, this context matters: if puts are heavy, selling CSPs into the fear can be lucrative if you believe the fear is overdone. But it's also riskier.`,
    dataSource: 'yfinance option_chain (on-demand, top 100 names only)',
  },
  {
    num: 6,
    name: 'Volume/OI Ratio',
    signal: 'volume_oi_ratio',
    weight: 0.10,
    threshold: 'Vol/OI > 0.30',
    what: "Measures daily options activity relative to standing open positions.",
    math: `total_vol = puts_volume + calls_volume
total_oi = puts_open_interest + calls_open_interest
ratio = total_vol / total_oi

score = min(1.0, (ratio - 0.30) / 0.30) if fired, else 0.0`,
    whyThreshold: `Open interest is the "installed base" of options positions. Volume is today's activity. A ratio above 0.30 means today's trading is rotating 30%+ of the entire position base — unusual. Above 0.60 suggests block trades, sweeps, or significant repositioning.`,
    tradingMeaning: `High vol/OI ratios indicate that smart money is actively repositioning in this name's options. New positions are being opened (or closed) at an unusual rate. This often precedes the kind of volatility that creates premium selling opportunities.`,
    dataSource: 'yfinance option_chain (on-demand, top 100 names only)',
  },
  {
    num: 7,
    name: 'Correlation Breakdown',
    signal: 'correlation_breakdown',
    weight: 0.15,
    threshold: 'Breakdown \u2265 0.3',
    what: "Measures how much a stock has recently decoupled from the S&P 500 (SPY).",
    math: `Compute Pearson correlation of daily returns:
- corr_long = correlation over 60 days (baseline)
- corr_short = correlation over 20 days (recent)

breakdown = corr_long - corr_short

Returns are used (not prices) to avoid spurious correlation from shared trends.`,
    whyThreshold: `A breakdown of 0.3 means the 20-day correlation has dropped 0.3 points below the 60-day average. For a stock that normally correlates 0.7 with SPY, this means recent correlation is 0.4 — the stock is moving independently. This is a fixed threshold; per-name robust z-score normalization is planned but deferred.`,
    tradingMeaning: `When a stock decouples from the market, it's experiencing an idiosyncratic (name-specific) event. The market isn't moving it — something specific to the company is. This often means elevated IV with a specific catalyst, which can create premium selling setups if you understand the catalyst.`,
    dataSource: 'historical_bars table (symbol + SPY)',
  },
  {
    num: 8,
    name: 'Earnings Proximity',
    signal: 'earnings_proximity',
    weight: 0.15,
    threshold: '1-14 days until earnings',
    what: "Detects upcoming earnings announcements and scores by proximity.",
    math: `If next earnings is 1-14 days away:
  score = 1.0 - (days_until - 1) / 14

1 day out = score 1.0
7 days out = score 0.57
14 days out = score 0.07

SPECIAL: If this rule fires, the entire composite score gets multiplied by 1.5\u00d7 after all other rules are scored. This is the earnings amplification.`,
    whyThreshold: `14 days captures the "IV ramp" — the period where options premiums steadily increase as earnings approach. The linear decay prioritizes names closest to their event. The 1.5\u00d7 amplification is intentional double-counting: earnings names deserve outsized attention because they have both elevated IV (premium opportunity) and elevated risk (gap risk).`,
    tradingMeaning: `Earnings is the single biggest catalyst for IV expansion. Premium sellers can profit from the IV crush that happens after the announcement — but must avoid holding through the event (gap risk). The system uses this signal to surface names worth evaluating, then applies a hard constraint: NEVER sell puts within 7 days of earnings.`,
    dataSource: 'earnings_event table (Finnhub bulk API)',
  },
  {
    num: 9,
    name: 'Short Interest',
    signal: 'short_interest',
    weight: 0.10,
    threshold: '>10% of float OR >5.0 days to cover',
    what: "Measures short selling pressure via two metrics.",
    math: `pct_of_float = shares_shorted / shares_outstanding
days_to_cover (short ratio) = shares_shorted / avg_daily_volume

Fires if pct_of_float > 0.10 OR days_to_cover > 5.0
pct_score = min(1.0, (pct - 0.10) / 0.10)
ratio_score = min(1.0, (ratio - 5.0) / 5.0)
final_score = max(pct_score, ratio_score)`,
    whyThreshold: `10% short interest is well above the market average (~3-5%). Days to cover above 5 means it would take a week of average volume for shorts to close — creating squeeze potential. Either metric indicates significant bearish positioning.`,
    tradingMeaning: `High short interest creates two dynamics: (1) potential short squeezes that spike IV, and (2) a floor of buying demand as shorts eventually cover. Both create premium selling opportunities. But heavily shorted names are shorted for a reason — the signal needs corroboration from other rules.`,
    dataSource: 'yfinance Ticker.info (on-demand, top 100 names only)',
  },
  {
    num: 10,
    name: 'News Density',
    signal: 'news_density',
    weight: 0.15,
    threshold: 'Z \u2265 2.0',
    what: "Measures whether a name is getting abnormally many headlines compared to its 30-day baseline.",
    math: `count_24h = headlines in last 24 hours
avg_daily = total_headlines_30d / 30
std_daily = sqrt(max(avg_daily, 0.1))  (Poisson approximation)

z = (count_24h - avg_daily) / std_daily

Requires \u22655 distinct days of news history. Uses mean/stdev (not robust) because news counts are Poisson-like, not fat-tailed.`,
    whyThreshold: `z \u2265 2.0 means today's headline count is roughly double the typical daily rate. This filters noise (stock always gets 5 headlines/day) from signal (stock normally gets 2 headlines/day, today got 8). The Poisson approximation handles names with sparse news coverage.`,
    tradingMeaning: `A spike in media attention often precedes or accompanies price volatility. For the vol_reversion sleeve, LOW news density with high IV is actually the desired signal (unexplained vol spike = likely reversion). For event_driven, HIGH news density + earnings = catalyst confirmation.`,
    dataSource: 'symbol_news_headlines table (Finnhub, on-demand for top 200)',
  },
  {
    num: 11,
    name: 'Social Mention Velocity',
    signal: 'social_velocity',
    weight: 0.10,
    threshold: '>10 messages in 24h',
    what: "Measures retail sentiment velocity via StockTwits message count.",
    math: `mentions_24h = count of StockTwits messages in last 24 hours

score = min(1.0, (mentions - 10) / 20)
Scales from 0 at threshold (10) to 1.0 at 3\u00d7 threshold (30 messages).`,
    whyThreshold: `10 messages in 24 hours indicates active retail discussion. Below 10 is background noise. The signal is weakest of the 11 (0.10 weight) because social media is noisy and often lags price action. But in combination with other signals, it confirms that retail is aware of whatever is happening.`,
    tradingMeaning: `Social media attention tends to spike after moves, not before. Its value is confirming that a setup isn't just a mechanical blip — real people are discussing it. This matters more for the event_driven sleeve (catalyst + attention = momentum) than vol_reversion (which prefers quiet names).`,
    dataSource: 'StockTwits API (on-demand, top 50 names only, 1.8s pacing)',
  },
]

// ── Main Page ────────────────────────────────────────────────

export default function RulesPage() {
  const [fireRates, setFireRates] = useState({})
  const [fireRatesError, setFireRatesError] = useState(false)

  useEffect(() => {
    fetchDashboardSignals(14)
      .then(d => {
        const rates = {}
        for (const s of d.signals || []) {
          rates[s.signal] = s.rate
        }
        setFireRates(rates)
        setFireRatesError(false)
      })
      .catch(() => setFireRatesError(true))
  }, [])

  return (
    <div className="w95" style={{ minHeight: '100%' }}>
      <div className="w95-page">

        {/* The Funnel */}
        <W95Window title="The Funnel" icon="&#128376;">
          <FunnelPanel />
        </W95Window>

        {/* Daily Schedule */}
        <W95Window title="Daily Schedule (All Times ET)" icon="&#128339;">
          <SchedulePanel />
        </W95Window>

        {/* Pre-Filters */}
        <W95Window title="Pre-Filters" icon="&#128683;">
          <Expandable title="Liquidity Floor: min $10M daily dollar volume" defaultOpen>
            <p style={{ margin: '0 0 6px 0' }}>
              <Label>What:</Label> Before any rules are scored, names with daily dollar volume below $10,000,000 are hard-rejected.
            </p>
            <p style={{ margin: '0 0 6px 0' }}>
              <Label>Why:</Label> Low-liquidity names have wide bid/ask spreads on their options. A CSP with a $0.50 spread on a $1.00 premium means you're giving up 50% of your edge to the market maker. The $10M floor ensures you're trading names where the options market is deep enough for reasonable fills.
            </p>
            <p style={{ margin: 0 }}>
              <Label>Applied:</Label> Before Rule 1. Names below the floor never enter the scoring pipeline.
            </p>
          </Expandable>
          <Expandable title="Min History Guard: 60 trading days required">
            <p style={{ margin: '0 0 6px 0' }}>
              <Label>What:</Label> Rules 1, 2, 3, and 7 require at least 60 days of price history in the historical_bars table. Rule 4 requires history for its per-name IV rank delta distribution.
            </p>
            <p style={{ margin: '0 0 6px 0' }}>
              <Label>Why:</Label> Z-scores computed against fewer than 60 days are statistically unreliable. With 20 data points, a single outlier shifts the median by 5%. With 60 points, the same outlier shifts it by &lt;2%. IPOs and recently listed names fail this guard until they accumulate enough history.
            </p>
            <p style={{ margin: 0 }}>
              <Label>Applied:</Label> Per-rule. A name can pass Rule 8 (earnings) even if it fails the history guard on Rule 1 (volume).
            </p>
          </Expandable>
        </W95Window>

        {/* The 11 Rules */}
        <W95Window title="The 11 Rules" icon="&#128209;">
          {RULES.map(rule => {
            const rate = fireRates[rule.signal]
            const rateStr = rate != null ? `${rate.toFixed(1)}%` : fireRatesError ? 'No data' : '...'
            return (
              <Expandable
                key={rule.num}
                title={
                  <span>
                    Rule {rule.num}: {rule.name}
                    <span style={{ fontWeight: 'normal', color: '#808080', marginLeft: 12, fontSize: 10 }}>
                      weight: {rule.weight} | threshold: {rule.threshold} | fire rate: {rateStr}
                    </span>
                  </span>
                }
              >
                <p style={{ margin: '0 0 8px 0' }}>
                  <Label>What it measures:</Label> {rule.what}
                </p>

                <div style={{
                  border: '2px inset #dfdfdf',
                  background: '#f8f8f0',
                  padding: '6px 8px',
                  marginBottom: 8,
                  fontFamily: 'var(--w95-font-mono)',
                  fontSize: 11,
                  lineHeight: 1.6,
                  whiteSpace: 'pre-wrap',
                }}>
                  <Label>The math:</Label>{'\n'}{rule.math}
                </div>

                <p style={{ margin: '0 0 8px 0' }}>
                  <Label>Why this threshold:</Label> {rule.whyThreshold}
                </p>

                <p style={{ margin: '0 0 8px 0' }}>
                  <Label>What it means for trading:</Label> {rule.tradingMeaning}
                </p>

                <div style={{ display: 'flex', gap: 16, fontSize: 10, color: '#808080' }}>
                  <span><Label>Data source:</Label> {rule.dataSource}</span>
                  <span><Label>Weight:</Label> <Mono>{rule.weight}</Mono></span>
                  <span><Label>Fire rate (14d):</Label> <Mono>{rateStr}</Mono></span>
                </div>
              </Expandable>
            )
          })}
        </W95Window>

        {/* Scoring & Combination */}
        <W95Window title="Scoring & Combination" icon="&#128290;">
          <div style={{ fontSize: 11, lineHeight: 1.7, fontFamily: 'var(--w95-font-ui)' }}>
            <p style={{ margin: '0 0 8px 0' }}>
              <Label>How individual scores combine into a composite:</Label>
            </p>

            <p style={{ margin: '0 0 6px 0' }}>
              Each rule produces a score between 0.0 and 1.0. Rules that don't fire contribute 0.0. The composite is a weighted sum:
            </p>

            <div style={{
              border: '2px inset #dfdfdf',
              background: '#f8f8f0',
              padding: '6px 8px',
              marginBottom: 8,
              fontFamily: 'var(--w95-font-mono)',
              fontSize: 11,
              whiteSpace: 'pre-wrap',
            }}>
{`composite = (vol_z \u00d7 0.20) + (range \u00d7 0.15) + (gap_z \u00d7 0.15) + (iv_delta \u00d7 0.20)
          + (corr \u00d7 0.15) + (earnings \u00d7 0.15) + (news \u00d7 0.15)
          + (p/c \u00d7 0.10) + (vol/oi \u00d7 0.10) + (short \u00d7 0.10) + (social \u00d7 0.10)

Total possible = 1.55 (if every rule fires at score 1.0)

After scoring, if earnings fired: composite \u00d7= 1.5
Max possible with amplification: 2.325`}
            </div>

            <Expandable title="2-Rule Minimum Gate">
              <p style={{ margin: '0 0 6px 0' }}>
                A name must fire <strong>at least 2 independent rules</strong> to be promoted to Tier 2 (was_considered = true). Single-signal names become "near-misses" — the top 30 are stored for inspection but not promoted.
              </p>
              <p style={{ margin: 0 }}>
                <Label>Why:</Label> A single elevated signal is usually noise. Volume spiked? Could be a block trade. IV rank jumped? Could be a data glitch. But volume spiked AND IV jumped AND correlation broke down? That's a pattern worth investigating.
              </p>
            </Expandable>

            <Expandable title="Earnings Amplification (1.5\u00d7)">
              <p style={{ margin: '0 0 6px 0' }}>
                When Rule 8 (Earnings Proximity) fires, the final composite score is multiplied by 1.5. This is applied <strong>after</strong> all individual rules are scored but <strong>before</strong> the 2-rule minimum gate.
              </p>
              <p style={{ margin: '0 0 6px 0' }}>
                <Label>Effect:</Label> Earnings contributes to the base score via its weight (0.15) AND amplifies the total. This is intentional double-counting — earnings names deserve outsized attention because they have the highest IV and the highest risk.
              </p>
              <p style={{ margin: 0 }}>
                <Label>Example:</Label> A name with composite 0.45 (vol_z + range fired) gets amplified to 0.675 if earnings is within 14 days. This pushes it above names with the same signals but no earnings catalyst.
              </p>
            </Expandable>

            <Expandable title='What "composite score of 1.51" means'>
              <p style={{ margin: '0 0 6px 0' }}>
                A composite of 1.51 means this name scored in the top tier of the system's attention. For context:
              </p>
              <ul style={{ margin: '0 0 6px 0', paddingLeft: 20 }}>
                <li><Mono>0.10 - 0.30</Mono>: 1-2 weak signals. Near-miss territory.</li>
                <li><Mono>0.30 - 0.60</Mono>: 2-3 moderate signals. Typical promotion.</li>
                <li><Mono>0.60 - 1.00</Mono>: Multiple strong signals. Worth serious evaluation.</li>
                <li><Mono>1.00 - 1.55</Mono>: Many rules firing strongly, or earnings amplification on a multi-signal name.</li>
                <li><Mono>&gt; 1.55</Mono>: Earnings amplification on an already hot name. Maximum system attention.</li>
              </ul>
              <p style={{ margin: 0 }}>
                The score is relative — what matters is the ranking. The Lead Agent sees the top candidates sorted by composite score and evaluates each one against regime, positions, and playbook.
              </p>
            </Expandable>

            <Expandable title="Current weights (equal) vs future learned weights">
              <p style={{ margin: '0 0 6px 0' }}>
                All rule weights are currently set by hand. The signal-weight learner (part of the learning loop) computes optimal weights from trade outcomes, but changes require backtester validation before deployment. During the 6-month experiment, no signal weight changes are allowed without validation.
              </p>
              <p style={{ margin: 0 }}>
                Per-sleeve weight overrides exist in each sleeve's YAML config. For example, the vol_reversion sleeve weights iv_rank_delta at 0.30 (vs default 0.20) because IV spike detection is its primary edge.
              </p>
            </Expandable>
          </div>
        </W95Window>

        {/* Key Concepts */}
        <W95Window title="Key Concepts" icon="&#128218;">
          <Expandable title="Z-Score">
            <p style={{ margin: 0 }}>
              How many "typical deviations" a value is from the center. A z-score of 2.0 means the value is unusually high — roughly in the top 2-5% of the distribution. We use <strong>robust z-scores</strong> (median/MAD) instead of classical z-scores (mean/stdev) because financial data has fat tails — a single outlier can inflate the mean and stdev, making everything else look normal by comparison.
            </p>
          </Expandable>
          <Expandable title="Median / MAD (Robust Statistics)">
            <p style={{ margin: 0 }}>
              The <strong>median</strong> is the middle value — unaffected by outliers. If 59 days have volume of 1M and one day has 50M, the mean is 1.8M (inflated) but the median is still 1M (correct). <strong>MAD</strong> (Median Absolute Deviation) is the median of |each value - median|, multiplied by 1.4826 to be comparable to standard deviation. Together, they give you a center and spread that a single extreme day can't distort.
            </p>
          </Expandable>
          <Expandable title="ATR (Average True Range)">
            <p style={{ margin: 0 }}>
              A per-name measure of daily price volatility. True Range = the largest of: (High - Low), |High - Previous Close|, |Low - Previous Close|. This captures gaps. We use the <strong>median</strong> of true ranges over 20 days (robust ATR) rather than the traditional mean.
            </p>
          </Expandable>
          <Expandable title="IV Rank (Implied Volatility Rank)">
            <p style={{ margin: 0 }}>
              Where current implied volatility sits in its 52-week range, as a percentile (0-100). IV Rank 80 means current IV is higher than 80% of the past year's readings. Premium sellers want <strong>high IV Rank</strong> because it means options are expensive relative to history — more premium to collect, with a higher probability of IV reverting downward.
            </p>
          </Expandable>
          <Expandable title="Open Interest vs Volume">
            <p style={{ margin: 0 }}>
              <strong>Open Interest</strong> = total number of outstanding option contracts (positions people are holding). <strong>Volume</strong> = number of contracts traded today. A high Volume/OI ratio means today's activity is unusually large relative to the installed base — new positions are being opened or existing ones closed at an elevated rate.
            </p>
          </Expandable>
          <Expandable title="Correlation Breakdown">
            <p style={{ margin: 0 }}>
              Most stocks move with the broad market (SPY). When a stock's correlation to SPY drops significantly over a short window, it means something specific to that company is driving the price — not the overall market. This "decoupling" often coincides with elevated IV and idiosyncratic risk, creating premium selling setups.
            </p>
          </Expandable>
          <Expandable title="Cash-Secured Put (CSP)">
            <p style={{ margin: 0 }}>
              Selling a put option while holding enough cash to buy 100 shares at the strike price if assigned. You collect premium upfront. If the stock stays above the strike, the put expires worthless and you keep the premium. If it drops below, you buy shares at the strike (minus premium received). This is the system's primary strategy.
            </p>
          </Expandable>
          <Expandable title="Per-Name Baselines">
            <p style={{ margin: 0 }}>
              Every statistical rule compares a name to <strong>its own history</strong>, not to the market. TSLA's "normal" volume is 50M shares; KO's is 8M. A z-score of 2.0 on TSLA requires proportionally more volume than on KO. This prevents high-volatility names from always firing and low-volatility names from never firing.
            </p>
          </Expandable>
          <Expandable title="Earnings Amplification">
            <p style={{ margin: 0 }}>
              When a name has earnings within 14 days, the entire composite score is multiplied by 1.5\u00d7. This is separate from Rule 8's base contribution. The effect is that earnings names get prioritized in the ranking — they appear near the top of the Lead Agent's candidate list, ensuring they get evaluated even if their other signals are moderate.
            </p>
          </Expandable>
        </W95Window>
      </div>
    </div>
  )
}
