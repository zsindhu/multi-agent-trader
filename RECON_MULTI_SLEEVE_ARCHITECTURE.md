# Multi-Sleeve Architecture Viability Recon

Generated: 2026-04-23
Status: Recon only — no code changes made

---

## Section 1: Current State Architectural Inventory

### Sleeve Abstraction

**No sleeve concept exists.** The closest analog is the worker pattern: three workers (CoveredCallWorker, CashSecuredPutWorker, WheelWorker) each own a strategy with params from `config/strategies.yaml`. Positions track `assigned_to` (agent name) in both `core/portfolio.py:Position` and `core/portfolio.py:OptionsPosition` dataclasses. The Lead Agent dispatches actions to workers by name.

**Minimum viable sleeve abstraction:** Each sleeve would be a named strategy configuration (not a new agent class) that the Lead Agent selects from. The existing `assigned_to` field on positions could store `"sleeve:yield_farming"` instead of `"Cash-Secured-Puts"`. Workers would receive the sleeve context along with the trade action. Config would expand from 3 strategy blocks to 10+ sleeve blocks, each specifying: target delta, DTE range, IV rank thresholds, universe filter criteria, capital allocation, and which Tier 2a signals matter most.

**Lead Agent strategy context:** The system prompt (`lead_agent.py:301-350`) includes hard constraints (max positions, position size caps, earnings blackout) and a decision framework. Strategy selection is implicit in the action type (`open_csp`, `open_cc`, `open_wheel`). The Lead Agent has full autonomy to choose which action to take — it's not constrained to a single strategy per cycle. This is actually well-suited for multi-sleeve: the Lead Agent already makes multi-strategy decisions, it just needs sleeve-tagged context.

### Tier 2a Rule Implementation (services/signal_compute.py)

| Rule | Function | Method | Threshold | Per-name baseline? | Median/MAD candidate? |
|------|----------|--------|-----------|--------------------|-----------------------|
| 1 | `volume_zscore()` | Mean/std z-score | z ≥ 2.0 | YES (60d window) | **YES** — volume distributions are heavily fat-tailed |
| 2 | `range_expansion_vs_atr()` | Fixed ATR ratio | ≥ 1.5x | Partial (ATR is per-name but uses mean) | **YES** — replace mean-ATR with median-ATR |
| 3 | `gap_zscore()` | Mean/std z-score | |z| ≥ 2.0 | YES (60d window) | **YES** — gap distributions are fat-tailed |
| 4 | `iv_rank_delta()` | Fixed absolute | |delta| ≥ 15 pts | NO | **YES** — per-name z-score would fix the 81.7% fire rate |
| 5 | `put_call_volume_ratio()` | Fixed absolute | >1.5 or <0.5 | NO | YES (future: per-name history table) |
| 6 | `volume_oi_ratio()` | Fixed absolute | >0.30 | NO | Less critical (ratio is already normalized) |
| 7 | `correlation_breakdown()` | Fixed absolute | drop ≥ 0.3 | NO | **YES** — per-name correlation baseline would help |
| 8 | `earnings_proximity()` | Linear decay | 1-14 days | N/A (event) | N/A |
| 9 | `short_interest_signal()` | Fixed absolute | >10% or >5 days | NO | YES (future: per-name history) |
| 10 | `news_density_zscore()` | Approximate z-score | z ≥ 2.0 | Partial (Poisson approximation) | Less critical |
| 11 | `social_velocity_signal()` | Fixed absolute | >10 messages | NO | YES (future: per-name history) |

**Key finding:** Rules 1, 3 use `_safe_mean()` and `_safe_std()` (lines 22-36 of signal_compute.py) — standard mean/std. These are the primary candidates for median/MAD migration. Rule 4's 81.7% fire rate confirms it needs per-name normalization, not just a threshold bump.

### Position Sizing Logic

**Sizing is determined by three layers:**
1. **RiskManager** (`core/risk_manager.py:52-62`): `calculate_position_size()` returns `max_dollar = equity × max_position_pct` (default 15%), reduced 50% in conservative mode. Output is a dollar amount, not a contract count.
2. **Lead Agent prompt** (line 322): "NEVER exceed {max_pct}% of equity in a single position" — the LLM sees this as a constraint but decides sizing within it.
3. **Worker execution**: Workers translate the dollar amount into contract counts based on strike × 100.

**No edge-weighted sizing exists.** The Lead Agent doesn't output an estimated edge. Its action JSON includes `contracts: N` but no confidence or edge estimate. Introducing Kelly-informed sizing would require: (a) adding an `estimated_edge` field to the action output schema, (b) adding a sizing function that converts edge to position size bounded by fractional Kelly, (c) the Risk Manager enforcing the bound.

### Risk Layer

**Current risk checks** (`core/risk_manager.py`):
- Portfolio drawdown vs `max_drawdown` (default 10%) → triggers conservative mode
- Position size as % of equity (default 15% cap)
- Per-agent position count limit (default 5 CSP, 5 CC, 3 Wheel)
- Cash collateral check for CSPs
- Share availability check for CCs

**What's missing for multi-sleeve:**
- No sector concentration limits
- No cross-position correlation limits
- No Greek exposure limits (aggregate delta, vega, theta)
- No per-sleeve capital tracking
- No cross-sleeve name collision prevention

**Cleanest insertion point:** A new `SleeveRiskGate` class that sits between the Lead Agent's action dispatch and worker execution. The Lead Agent decides what to trade; the risk gate decides whether the trade is permitted. This preserves LLM autonomy on strategy while enforcing hard constraints.

### Configuration Granularity

`config/tier2a.yaml` uses a flat `rules:` dict with per-rule sub-dicts. **Per-sleeve rule weighting is NOT expressible** in the current format. It would require either:
- (a) Multiple config files (`config/sleeve_yield_farming.yaml`, etc.)
- (b) A nested structure: `sleeves: { yield_farming: { rules: { ... } } }`
- (c) An override layer: base weights in tier2a.yaml, per-sleeve weight overrides in a separate file

Option (a) is simplest and matches the existing pattern of separate config files per agent.

### Observation Tagging

`name_observations` has no `sleeve_id` field. Adding one is a single-column migration (nullable String, indexed). Non-disruptive to existing data — old rows get NULL. `cycle_snapshots` is portfolio-scoped (one row per Lead Agent cycle, not per sleeve). Multi-sleeve would need either a `sleeve_context` JSON field in the existing table or a new `sleeve_cycle_snapshots` table.

---

## Section 2: Robust Statistics Migration Scope

### Functions to change

1. **`_safe_mean()` → `_safe_median()`** and **`_safe_std()` → `_safe_mad()`** in `signal_compute.py` (lines 22-36). MAD = median(|xi - median(x)|) × 1.4826 (scaling factor for normal-equivalent).

2. **`volume_zscore()`** (line 55-78): Replace `z = (today - mean) / std` with `z = (today - median) / mad`. Same threshold (z ≥ 2.0), different baseline.

3. **`gap_zscore()`** (line 128-164): Same replacement.

4. **`range_expansion_vs_atr()`** (line 83-123): Replace `_safe_mean(true_ranges)` with `_safe_median(true_ranges)` for the ATR computation.

5. **Rule 4 `iv_rank_delta()`**: Needs redesign — convert from fixed 15-point threshold to per-name z-score of the 5-day IV rank change vs its own 60-day distribution.

### Computational cost

Median computation is O(n log n) vs mean's O(n). For 60-element arrays, the difference is negligible (<1ms). MAD requires two passes (median, then median of deviations). At 525 promoted names × 3 cycles/day, total additional compute: <1 second per cycle. **No performance concern.**

scipy is installed (`scipy>=1.11.0` in requirements.txt) and provides `scipy.stats.median_abs_deviation()`, but the computation is trivial enough to implement in pure Python (like the existing `_safe_std`).

### Backward compatibility

**Recommend keeping both for a comparison period.** Add `_safe_median()` and `_safe_mad()` alongside existing functions. Signal output dicts can include both: `"raw_zscore": 2.5, "raw_robust_zscore": 3.1`. The signal-weight learner can evaluate which produces better outcome predictions. After validation, deprecate the mean/std versions.

### Signal-weight learner impact

The learner's existing 23 pre-funnel outcomes have **zero value** for post-migration evaluation — they were labeled against mean/std scores. After migration, the learner needs new funnel-driven outcomes computed against robust scores. The 50-sample minimum gate handles this naturally — it won't retrain until enough new data accumulates.

---

## Section 3: The 10-Sleeve Architecture Viability

### Sleeve 1: Yield-farming premium (far-OTM CSPs + CCs on stable large-caps)

- **Data:** ✅ All needed data exists (IV rank, options chains, historical bars)
- **Signals:** Rules 1 (volume), 4 (IV rank), 8 (earnings) are relevant. Rules 2,3,7 (change-detection) are counterproductive — this sleeve wants stable names, not volatile ones.
- **Execution:** ✅ Single-leg CSPs and CCs fully supported
- **Capital:** At $50K, ~5-8 CSPs at $30-50 strikes. Coherent.
- **Verdict: VIABLE NOW.** Needs a sleeve-specific scanner that filters for low-vol, high-liquidity names with IV rank 20-40 (not high IV).

### Sleeve 2: Event-driven premium (sell into elevated IV before earnings)

- **Data:** ✅ Earnings calendar (universe-scale), IV rank, options chains
- **Signals:** Rules 4 (IV delta), 8 (earnings proximity) are primary. Rule 10 (news density) is useful context.
- **Execution:** ✅ Single-leg CSPs/CCs
- **Capital:** At $50K, ~3-5 positions. Concentrated but coherent.
- **Verdict: VIABLE NOW.** The earnings proximity rule + IV rank delta are already the highest-leverage signals in Tier 2a. This sleeve is essentially "what the system already does well, made explicit."

### Sleeve 3: Implied-vs-realized vol arbitrage

- **Data:** ⚠️ Partial. IV is available from Alpaca options snapshots. Realized vol computed from historical_bars. The comparison (IV > realized) requires a per-name IV surface that doesn't currently exist — IV rank is a percentile, not the actual implied vol level.
- **Signals:** Rule 4 (IV delta) is relevant. Need new signal: `iv_premium = current_iv - realized_vol_20d`. Computable from existing data.
- **Execution:** ✅ Single-leg (sell straddles would need multi-leg — deferred)
- **Capital:** At $50K, ~5-8 positions. Coherent.
- **Verdict: VIABLE with ~40 lines of new signal code.** The `iv_premium` signal is the missing piece.

### Sleeve 4: Index credit spreads (SPY/QQQ/IWM put/call spreads)

- **Data:** ✅ Index options available via Alpaca
- **Signals:** Rules 1-7 are mostly irrelevant (these are single-name signals). Needs regime-level signals (VIX term structure, SPY trend, breadth).
- **Execution:** 🔴 **BLOCKED — multi-leg orders not supported.** Credit spreads require simultaneous buy + sell of different strikes. Alpaca supports this via their API but it's not implemented in `alpaca_broker.py`.
- **Capital:** At $50K, ~10-20 narrow spreads. Very coherent for defined-risk.
- **Verdict: BLOCKED until multi-leg support is added (~50 lines in alpaca_broker.py).**

### Sleeve 5: Vol mean reversion (IV rank spike >80, no catalyst, sell vol)

- **Data:** ✅ IV rank, earnings calendar, news density
- **Signals:** Rule 4 (IV delta) is primary. Need inverse logic: fire when IV rank is extremely HIGH and news density is LOW (no catalyst explaining the spike).
- **Execution:** ✅ Single-leg strangles need multi-leg, but single-leg CSPs/CCs work.
- **Capital:** At $50K, ~3-5 high-IV positions. Coherent but concentrated.
- **Verdict: VIABLE NOW.** The signal inversion (high IV + low news = unexplained spike) is ~20 lines of new signal code.

### Sleeve 6: Post-earnings IV residual (days 1-5 after earnings, sell residual IV)

- **Data:** ✅ Earnings calendar has event dates. Options chains available.
- **Signals:** Inverse of rule 8 — instead of "earnings approaching," detect "earnings just happened." Need `days_since_earnings` computed from earnings_events table.
- **Execution:** ✅ Single-leg
- **Capital:** At $50K, ~5-8 positions in the post-earnings window. Coherent.
- **Verdict: VIABLE with ~30 lines of new signal code.** Simple date arithmetic on the earnings calendar.

### Sleeve 7: Sector rotation premium (sector ETFs with macro-driven IV)

- **Data:** ✅ Sector ETF data (XLF, XLE, XLK, XLV, etc. already in always_include list). FRED macro data. Market regime service.
- **Signals:** Rule 7 (correlation breakdown) is the primary signal. FRED yield curve, VIX term structure as additional context.
- **Execution:** ✅ Single-leg on sector ETFs
- **Capital:** At $50K, ~5-8 ETF positions. Very coherent.
- **Verdict: VIABLE NOW.** Sector ETFs are already in the Tier 1 universe. The macro context from FRED + regime service provides the rotation thesis.

### Sleeve 8: Term structure / VIX plays

- **Data:** 🔴 **BLOCKED.** VIX futures data not available from any current feed. VIX spot is available (Yahoo Finance via vix_service.py), but VIX futures term structure requires a separate data source (CBOE, or VIX futures from a futures broker).
- **Signals:** None of the 11 rules apply.
- **Execution:** 🔴 **BLOCKED.** Alpaca doesn't support VIX futures. VIX options would need a VIX options chain endpoint.
- **Capital:** N/A
- **Verdict: NOT VIABLE. Requires new data feed + new execution capability.** Remove from the 10-sleeve plan.

### Sleeve 9: Skew trading (put/call skew extremes)

- **Data:** ⚠️ Partial. Options chains provide IV per strike, but computing skew (IV at 25-delta put vs 25-delta call) requires interpolation across the chain. Rule 5 (P/C ratio) is a proxy but not the same thing.
- **Signals:** Rule 5 is a rough proxy. Need a proper `skew_score` signal that computes 25d put IV / 25d call IV from the options chain.
- **Execution:** ✅ Single-leg (sell the expensive side)
- **Capital:** At $50K, ~5-8 positions. Coherent.
- **Verdict: VIABLE with ~60 lines of new signal code** (skew computation from options chain data already fetched for rules 5/6).

### Sleeve 10: Pairs / stat arb (correlation-breakdown pairs)

- **Data:** ✅ Historical bars for correlation computation. Rule 7 already detects correlation breakdowns.
- **Signals:** Rule 7 is the primary signal. Need a pairs scanner that identifies the correlated peer and computes the spread.
- **Execution:** ⚠️ Requires simultaneous positions in two names — not multi-leg per se, but does require paired position tracking.
- **Capital:** At $50K, ~3-5 pairs. Tight but coherent.
- **Verdict: VIABLE with ~100 lines** (pairs identification + spread computation). Most complex of the viable sleeves.

### Summary Table

| Sleeve | Viable? | New code | Blocked by |
|--------|---------|----------|------------|
| 1. Yield farming | ✅ NOW | ~0 (config only) | — |
| 2. Event-driven | ✅ NOW | ~0 (config only) | — |
| 3. IV vs realized | ✅ EASY | ~40 lines | — |
| 4. Index spreads | 🔴 BLOCKED | ~50 lines | Multi-leg orders |
| 5. Vol mean reversion | ✅ NOW | ~20 lines | — |
| 6. Post-earnings | ✅ EASY | ~30 lines | — |
| 7. Sector rotation | ✅ NOW | ~0 (config only) | — |
| 8. VIX term structure | 🔴 BLOCKED | Large | VIX futures data + execution |
| 9. Skew trading | ✅ MODERATE | ~60 lines | — |
| 10. Pairs / stat arb | ✅ MODERATE | ~100 lines | — |

**8 of 10 sleeves are viable.** Sleeves 4 and 8 are blocked on infrastructure (multi-leg orders and VIX futures data respectively).

---

## Section 4: Risk Framework Design Recommendations

### Proposed Hard Limits

| Limit | Value | Rationale | Computation |
|-------|-------|-----------|-------------|
| **Max position per sleeve** | 15% of sleeve capital | Kelly never recommends >25% even at high edge; 15% leaves buffer | `notional / sleeve_capital` |
| **Max sector concentration** | 30% of total portfolio in any one GICS sector | Prevents all-energy or all-tech concentration | Requires sector classification per symbol (available via Alpaca assets) |
| **Max single-name across sleeves** | 10% of total portfolio | Prevents 3 sleeves all trading AAPL | Sum notional across sleeves for each underlying |
| **Max loss per position** | 100% of premium received (CSPs) or 2x premium (spreads) | Defines max pain before mandatory close | Track entry premium vs current price |
| **Portfolio delta limit** | ±0.30 × portfolio notional | Prevents directional bet masquerading as premium selling | Sum delta × notional across all positions |
| **Portfolio vega limit** | Vega × notional < 2% of equity | Prevents catastrophic loss from vol spike | Sum vega exposure |
| **Per-sleeve drawdown trigger** | -10% of sleeve capital → pause sleeve for review | Early warning before capital destruction | Track sleeve-level equity curve |
| **Portfolio drawdown trigger** | -5% → reduce all sleeves to 50% sizing; -8% → halt new positions | Staged de-risking | Existing `risk_manager.py` pattern |

### New data requirements

- **Sector classification:** Alpaca's `get_tradable_assets()` returns exchange info but not GICS sector. yfinance `Ticker.info` has `sector` and `industry`. Need a sector lookup service (~30 lines).
- **Greek aggregation:** Alpaca options snapshots provide per-contract Greeks. Need a portfolio-level aggregator that sums delta, vega, theta across all open positions (~50 lines).
- **Per-sleeve capital tracking:** New table or config mapping sleeve → allocated capital. The Risk Manager needs to know each sleeve's budget.

---

## Section 5: Kelly-Informed Sizing

### Current state

The Lead Agent's action JSON includes `contracts: N` as a fixed integer. There's no `estimated_edge` field. The RiskManager computes a max dollar amount but the actual contract count is the Lead Agent's judgment.

### Proposed approach

1. **Add `estimated_edge` to the action output schema:** The Lead Agent's system prompt would include: "For each trade, estimate your edge as a probability of profit above 60% breakeven. Express as a decimal: 0.65 means you believe there's a 65% chance this trade is profitable."

2. **Sizing function:** `position_size = min(kelly_fraction × bankroll × edge / odds, max_position_size)` where `kelly_fraction = 0.25` (quarter-Kelly, conservative), `bankroll = sleeve_capital`, `edge = estimated_edge - 0.50`, `odds = premium / max_loss`.

3. **Enforcement:** The Risk Manager applies the sizing function AFTER the Lead Agent proposes a trade. If the agent suggests 3 contracts but Kelly says 1, the system sizes down to 1. The agent can't size UP beyond Kelly.

4. **Calibration:** After 50+ labeled outcomes, compare the Lead Agent's edge estimates to actual outcomes. If the agent consistently overestimates edge, apply a shrinkage factor. This feeds back into the learning flywheel.

5. **Implementation:** ~40 lines in a new `services/position_sizer.py` + 10 lines modifying the action dispatch in lead_agent.py.

---

## Section 6: Experiment Infrastructure

### What needs to exist before the 90-day experiment launches

1. **Experiment charter:** Pre-registered document specifying:
   - Which sleeves are active
   - Per-sleeve capital allocation
   - Success criteria (min Sharpe per sleeve? min win rate? max drawdown?)
   - Termination rules: what causes a sleeve to be shut down mid-experiment
   - Falsification conditions: what would prove the multi-sleeve thesis wrong

2. **Per-sleeve tracking:** Each trade tagged with sleeve_id. Daily PnL per sleeve computed and logged. This requires the `sleeve_id` migration on relevant tables.

3. **Evaluation dashboard at `/research/experiment`:** Per-sleeve Sharpe, drawdown, win rate, correlation to SPY, pairwise sleeve correlations. ~200 lines of new HTML route + SQL views.

4. **Sleeve correlation tracking:** Daily returns per sleeve, rolling 20-day pairwise Pearson correlations. New materialized computation — either a nightly cron or computed on-demand for the dashboard. ~80 lines.

5. **Scaling trigger logic:** Pre-committed rules in the experiment charter: "If sleeve N achieves Sharpe > 1.5 over 60 days with drawdown < 5%, it qualifies for capital increase." The system records which sleeves qualify; human makes the actual capital decision.

6. **Sleeve termination:** Two types: (a) capital preservation — sleeve hits -10% drawdown → automatic pause, (b) performance evaluation — sleeve has negative Sharpe after 60 days → flagged for review, not auto-terminated.

### Estimated effort for experiment infrastructure:

- Sleeve_id migration + tagging: ~1 day
- Per-sleeve capital tracking + Risk Manager updates: ~2 days
- 8 sleeve configs + scanner customization: ~2 days
- Kelly sizing service: ~1 day
- Evaluation dashboard + correlation tracking: ~2 days
- Multi-leg orders (for sleeve 4, if included): ~1 day

**Total: ~9 engineering days to launch with 8 sleeves.**

---

## Section 7: Honest Viability Assessment

### Is this viable without a rewrite?

**Yes.** The current architecture is well-suited for this evolution. The key insight: the Lead Agent already makes multi-strategy decisions (it dispatches to CSP, CC, and Wheel workers). Sleeving is adding more strategies to the menu, not changing the restaurant's architecture.

The hardest part is not the code — it's the config and risk management. Each sleeve needs its own scanner criteria, its own risk parameters, and its own capital allocation. The Lead Agent needs to reason across sleeves when making decisions. But the bones are solid.

### Realistic effort estimate

- **Minimum viable (4 sleeves, no multi-leg):** 2 weeks
- **Full 8 viable sleeves with risk framework:** 4-5 weeks
- **Full 8 sleeves + Kelly sizing + experiment dashboard:** 6-7 weeks

### Minimum viable version: which 3-4 sleeves first?

1. **Sleeve 2: Event-driven premium** — highest alpha potential, already the system's strength
2. **Sleeve 5: Vol mean reversion** — cleanest signal (high IV + no catalyst), minimal new code
3. **Sleeve 7: Sector rotation** — diversifies away from single-name risk, uses existing ETF data
4. **Sleeve 1: Yield farming** — the "sleep well" sleeve, provides stable baseline returns

These 4 cover: event-driven alpha, vol arbitrage, macro-driven rotation, and income generation. They require zero new data feeds and minimal new signal code. They're coherent at $50K each ($200K total notional in paper).

### Architectural decisions that will make this harder

1. **CycleSnapshot is portfolio-wide.** Every cycle logs one row for the entire portfolio. Multi-sleeve needs per-sleeve cycle logging. This is a meaningful schema change.

2. **Workers are strategy-typed, not sleeve-typed.** A "yield farming CSP" and an "event-driven CSP" both route through CashSecuredPutWorker. The worker doesn't know which sleeve it's serving. Either workers become sleeve-aware or a routing layer maps sleeve actions to the right worker.

3. **Tier 2a is one pipeline.** Each sleeve may want different rule weights or thresholds. Running 8 Tier 2a pipelines in parallel (one per sleeve) would be expensive. Better approach: run Tier 2a once with the universal config, then let each sleeve's scanner filter the results using sleeve-specific criteria.

### Highest-risk unknowns

1. **Lead Agent context window pressure.** With 8 sleeves × 50 names each = 400 names in context, plus per-name signals and reasoning, the Claude context window and cost per cycle could 3x-4x. Need to validate that the Lead Agent can reason across 8 sleeves without degraded decision quality.

2. **Cross-sleeve interaction effects.** If three sleeves all want to sell puts on NVDA simultaneously, the portfolio concentrates in one name. The risk framework handles this, but the Lead Agent needs to understand the portfolio-level view, not just per-sleeve views. This is a prompt engineering challenge.

3. **Cost scaling.** Current ~$112/month baseline. 8 sleeves with more complex Lead Agent reasoning could push to $200-300/month. The $150 target may not hold without aggressive prompt caching (1.4.1.4) or moving more reasoning to Llama (cheaper per token).

4. **Calibration data scarcity.** The signal-weight learner needs 50+ outcomes per sleeve to produce meaningful weight updates. At ~2-3 trades per sleeve per week, that's 4-6 months per sleeve. The 90-day experiment will produce directional data but not statistically robust per-sleeve weight optimization.

---

## Pushback on the Briefing

### Sleeve 8 (VIX term structure) should be cut

VIX futures require a futures broker (not Alpaca), a separate data feed (CBOE), and different execution infrastructure. The effort-to-value ratio is poor relative to the other sleeves. Replace with a simpler VIX-based sleeve: "sell SPY puts when VIX > 25" — same thesis (vol mean reversion), implementable today.

### 10 sleeves is too many for the initial experiment

Recommend 4-5 sleeves for the 90-day paper experiment, not 10. Reasons: (a) Lead Agent context window can't reason well across 10 simultaneous strategies, (b) 50 trades per sleeve for calibration × 10 sleeves = 500 trades needed, which won't happen in 90 days, (c) operational complexity of monitoring 10 sleeves exceeds what one person can review daily. Start with 4, add sleeves based on results.

### The $500K notional is fine for paper but the $25K live deployment should start with 2 sleeves, not 3

At $25K total, 3 sleeves get $8.3K each. CSP collateral for a single $50 strike put is $5K. That's ~1.5 positions per sleeve — not enough to diversify within a sleeve. Either increase to $50K live or start with 2 sleeves at $12.5K each.

### Kelly sizing from LLM edge estimates will be unreliable initially

The Lead Agent has no track record of calibrated edge estimates. Quarter-Kelly on an uncalibrated estimate is still dangerous. Recommend: start with uniform sizing (all positions same size within a sleeve), collect edge estimate data for 90 days, THEN enable Kelly sizing once the calibration data shows the agent's estimates are directionally correct.

---

## Summary: Recommended Execution Order

1. **Robust statistics migration** (1 day) — Median/MAD for rules 1, 2, 3, 4, 7. Immediate quality improvement.
2. **Sleeve abstraction + 4 initial sleeves** (3-4 days) — Config + tagging + Risk Manager updates
3. **Risk framework** (2 days) — Hard limits table, sector lookup, Greek aggregation
4. **Experiment dashboard** (2 days) — `/research/experiment` with per-sleeve metrics
5. **Launch 90-day paper experiment** with 4 sleeves at $125K each
6. **After 30 days:** Evaluate whether to add sleeves 3, 6, 9
7. **After 90 days:** Kelly sizing calibration from collected edge estimates
8. **Live deployment:** Top 2 sleeves at $12.5K each ($25K total)
