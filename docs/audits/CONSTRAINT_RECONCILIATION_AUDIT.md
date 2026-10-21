# Constraint Reconciliation Audit

> **Status as of 2026-10-21 (deployed f51c4c5):** all findings below remain **open**.
> No commit since 2026-07-13 touches them: the dead sleeve config keys are still unread,
> the `min_iv_rank * 0.3` proxy is still at `agents/sleeve_orchestrator.py:292`, sleeve prompts
> still lack the earnings-ban hard constraint, and `regime_confidence` still has no writer.
> Tracked in BACKLOG.md.

Generated: 2026-07-13 · Recon only — no commits, no config changes, no fixes
Companion to FUNNEL_THROUGHPUT_AUDIT.md. All satisfiability numbers computed
against the real last-60-days promotion data (23,580 day-symbol promotions).

---

## 1. The Constraint Register

Every gate that can prevent a trade, source → requirement → **is it actually read at runtime?**

### Tier 2a mechanical gate (`config/tier2a.yaml` + `agents/tier2a_prefilter.py`)

| Constraint | Requirement | Read? |
|---|---|---|
| `min_signals_to_fire` | ≥2 of 11 change-detection rules fired | ✅ (`tier2a_prefilter.py:96`) — killed 124,354 name-days in 60d |
| `min_daily_dollar_volume` | ≥ $10M DDV | ✅ (`:98`) — killed 64,076 |
| per-rule thresholds (z≥2.0, ATR 1.5×, IV Δ≥15 pts, …) | rule-level firing | ✅ (`services/signal_compute.py`) |

### Sleeve scanner filters (`config/sleeves/*.yaml` → `sleeve_orchestrator._filter_promotions_for_sleeve:262-320`)

| Sleeve | Key | Requirement | Read? |
|---|---|---|---|
| event_driven | `require_earnings_within_days: 14` | earnings 1–14d out | ✅ `:275` |
| event_driven | `min_iv_rank_delta: 10` | \|IV Δ\| ≥ 10 | ✅ `:284` |
| event_driven | `exclude_post_earnings_days: 5` | no entry ≤5d after earnings | ❌ **DEAD — key never referenced** |
| vol_reversion | `min_iv_rank: 70` | IV rank ≥ 70 | ⚠️ **CRUDE PROXY** — implemented as \|IV Δ\| ≥ 21 (`min_iv_rank * 0.3`, `:290-292`); actual IV *rank* is on the observation row (`iv_rank` column) and is not consulted |
| vol_reversion | `max_news_density: 5` | low news (no catalyst) | ✅ `:306` |
| vol_reversion | `exclude_earnings_within_days: 7` | no earnings 1–7d | ✅ `:279` |
| sector_rotation | `asset_type: etf` + `require_symbols` (21 tickers) | SPDR/index universe only | ✅ `:296,301` |
| yield_farming | `min_daily_dollar_volume: 500M` | mega-cap liquidity | ✅ `:311` |
| yield_farming | `min_market_cap_proxy: 50B` | mega-caps only | ❌ **DEAD — key never referenced** |
| yield_farming | `max_iv_rank: 50` | moderate IV, not spikes | ❌ **DEAD — key never referenced** |
| yield_farming | `exclude_earnings_within_days: 14` | no earnings 1–14d | ✅ `:279` |
| all | cap | top **15** per sleeve reach the prompt | ✅ `:320` |

### Sleeve strategy params (`config/sleeves/*.yaml → strategy:` → `services/sleeve_config.py`)

| Key | Where it goes | Actually enforced? |
|---|---|---|
| `delta_target` (−0.15…−0.25) | interpolated into the sleeve **prompt text** (`:381`) and the example json | ❌ **ADVISORY ONLY** — `lead_agent._execute_action:1151-1176` passes only the SYMBOL to the worker; the action's `delta`/`dte_target` fields are discarded. Workers trade `strategies.yaml` params. |
| `dte_min/dte_max` (e.g. yield 30–60) | prompt text only | ❌ same — and worse: workers search chains at `strategies.yaml` DTE 20–45, so **yield_farming's desired 46–60 DTE contracts are never even fetched** |
| `profit_target_pct` (vol_reversion 0.50) | nothing | ❌ DEAD — worker hardcodes its own 0.50 (`worker_csp.py:79`) |
| `close_before_earnings: true` (event_driven) | nothing | ❌ DEAD — zero references |
| `max_concurrent_positions` | risk gate (`run_cycle:149`) | ✅ enforced |
| `capital_allocation` | risk gate + prompt | ✅ |
| `weight_overrides` (all 4 sleeves, 5–7 signals each) | `SleeveConfig.get_weight` accessor exists (`sleeve_config.py:53`) | ❌ **DEAD — zero callers anywhere.** Tier 2a scores with universal weights; the per-sleeve signal-weighting layer described in the sleeve YAMLs was never wired. |

### LLM prompt hard rules

**Legacy lead prompt** (`agents/lead_agent.py`, "## Hard Constraints (never violate these)") — verbatim:
> - NEVER sell puts on a symbol with earnings within 7 days
> - NEVER deploy more than 80% of available buying power
> - NEVER have more than {max_pos} positions open per worker
> - NEVER exceed {max_pct}% of equity in a single position

**Sleeve prompt** (`sleeve_orchestrator._build_sleeve_prompt:371-410`) — contains **none of the above**. Its only constraints are max positions / delta / DTE / capital (all advisory, see previous table) and position-management rules ("Take profit at 50%", "Close ITM <5 DTE", "Close >50% underwater"). **The 7-day earnings ban reaches sleeves only culturally** — via briefing/playbook text and model priors — yet the observed reasoning enforces it strictly ("earnings 3 days — DISQUALIFIED"). An unwritten rule is doing written-rule work.
Also prompt-culture (from playbook/briefing, quoted in cycle reasoning): "3+ signals" quality bar (tier2a promotes at 2), the yield-farming "'sleep well' mandate".

### Worker / chain / risk layers

| Constraint | Source | Read? |
|---|---|---|
| min IV rank 25 (CSP), delta −0.25 window, DTE 20–45, support buffer 5% | `config/strategies.yaml` via worker params | ✅ — these, not the sleeve's, govern actual contract selection |
| `min_open_interest=10` | `data/options_chain.py:251` | ✅ |
| one position per symbol per worker | `worker_csp.evaluate` | ✅ |
| collateral check (`can_sell_put`), per-worker position cap, drawdown→conservative mode | `core/risk_manager.py` | ✅ |
| SleeveRiskGate: per-sleeve max positions, cross-sleeve name conflict, single-name concentration, sector ≤30%, capital ≤80%, sleeve DD ≤10%, portfolio DD ≤8% | `services/sleeve_risk_gate.py:51-130` | ✅ — but rejected only **1 trade in 60 days**; rejection reasons go to logs only (not persisted) |
| worker close-direction + duplicate-order guards | `worker_*.py` (July 8) | ✅ |
| TIF = `day` on every order | hardcoded in all 3 workers | ✅ (no config key exists) |

**Dead-key total: 6** — `exclude_post_earnings_days`, `max_iv_rank`, `min_market_cap_proxy`, `profit_target_pct` (sleeve-level), `close_before_earnings`, `weight_overrides` (all four sleeves' entire blocks). Plus 2 advisory-only (`delta_target`, `dte_min/max`) and 1 crude proxy (`min_iv_rank`).

---

## 2. Contradictions & joint satisfiability (real 60-day data)

Method: replicated the exact filter code over 23,580 day-symbol promotions; then layered the prompt-culture constraints (7-day earnings ban, 3+ fired signals). "Full stack" = everything that in practice must hold simultaneously before the LLM would even consider a name.

| Sleeve | Config-only eligible/day | **Full-stack eligible/day** | Zero-days /60 | Verdict |
|---|---|---|---|---|
| event_driven | 19.8 | **3.1** | 14 | The known keyhole, quantified: requires earnings 1–14d, culture bans ≤7d → lives in 8–14d, then the 3-signal bar kills 84% of what config passes |
| vol_reversion | 185.9 | **72.8** | 0 | No starvation whatsoever — inaction here is pure judgment |
| sector_rotation | 1.4 | **0.5** | **45** | Structurally starved even with its full 21-symbol whitelist |
| yield_farming | 43.2 | **14.9** | 0 | Supply exists daily; inaction is mandate/judgment |

Contradiction list:

1. **event_driven earnings keyhole** (config `require ≤14d` × culture `never ≤7d` × dead `exclude_post_earnings_days`): 8–14-day window, 3.1 candidates/day survive, and July's earnings wave makes even those get one-by-one disqualified in reasoning.
2. **yield_farming thesis vs. funnel mechanism**: charter thesis = "stable large-caps, moderate IV, sleep well." Its own weight_overrides say "we WANT stability, not activity" — but those weights are dead, and the sleeve can only see names that fired ≥2 *change-detection* (anomaly) signals. **The sleeve's stated selection principle is unimplementable through the funnel that feeds it.** The two keys that encoded "moderate IV" and "mega-cap" (`max_iv_rank`, `min_market_cap_proxy`) are both dead.
3. **sector_rotation universe vs. anomaly gate**: 21 staid index/sector ETFs must out-anomaly 4,300 single names to get promoted. 0.5 full-stack candidates/day; "No candidates for this sleeve" 45/60 days. Coherently implemented, structurally starving.
4. **Sleeve strategy params vs. execution reality**: the LLM is told delta −0.15 / DTE 30–60 (yield), decides accordingly, and the worker then shops a −0.25 / 20–45 chain. Any LLM decision predicated on sleeve-specific structure is silently re-parameterized at execution. This is a plausible contributor to the 4 decided-but-never-submitted opens (chain search returns nothing matching what the LLM approved).
5. **vol_reversion "IV rank ≥70" vs. its proxy**: intent is a level (rank 70+); implementation is a *change* (\|Δ\|≥21). Names with chronically-high-but-stable IV — the actual mean-reversion setup — are invisible; names with violent IV moves from a low base pass.
6. **3-signal culture bar vs. 2-signal promotion gate**: tier2a's contract is "2+ signals = worth a look"; the sleeves' inherited standard is 3+. Half the funnel's output is dismissed on arrival by an unwritten rule.

---

## 3. Classification — (a) BUG / (b) DESIGN FLAW / (c) POLICY

### (a) BUG — fixable without touching experiment integrity
1. `exclude_post_earnings_days` dead (event_driven)
2. `max_iv_rank` dead (yield_farming)
3. `min_market_cap_proxy` dead (yield_farming)
4. `weight_overrides` dead (all four sleeves — an entire designed layer, never wired)
5. `close_before_earnings` dead (event_driven — a **risk control** that silently doesn't exist)
6. `profit_target_pct` (sleeve) dead — worker hardcodes 0.50
7. `min_iv_rank` implemented as a Δ-proxy contradicting its stated intent (vol_reversion)
8. Sleeve `delta_target`/`dte_*` advisory-only; action's `delta`/`dte_target` discarded by `_execute_action` — LLM-approved structure silently re-parameterized
9. Sleeve prompts omit the hard-constraints block entirely (earnings ban, 80% BP, position caps live only in the legacy prompt) — currently enforced by luck/culture, not by instruction
10. Risk-gate rejection reasons not persisted (observability bug, blocks future audits)
11. `regime_confidence` written by nothing, read by nothing, advertised in the chat schema doc

### (b) DESIGN FLAW — coherent code, structurally starving
1. **sector_rotation**: single-name anomaly rules applied to 21 index ETFs → 0.5 eligible/day, zero-days 45/60. The type case.
2. **yield_farming fed by an anomaly funnel**: a baseline-income sleeve that can only see names flagged for *unusual change*. Its thesis requires a screener (stability, liquidity, moderate IV); it gets a tripwire.
3. **event_driven keyhole**: each constraint defensible; their intersection (8–14d × IVΔ × quality bar × Q2 calendar) yields 3.1/day and July famine.
4. **Single-shot day-limit execution** at scored price, no repricing: 45% fill rate as designed behavior (also flagged in throughput audit).

### (c) POLICY — deliberate strictness; walled off, touch only via charter amendment
1. The 7-day earnings ban itself (its *non-propagation to sleeve prompts* is bug (a)9; the rule is policy)
2. The "3+ signals" quality bar the agents apply
3. The yield-farming "sleep well" mandate (its rejection of BABA was reasoned, on-thesis judgment)
4. tier2a's 2-of-11 gate and per-rule thresholds
5. Delta/DTE targets per sleeve (as intents; their enforcement path is bug (a)8)
6. Risk-gate limits (sector 30%, single-name, 80% capital, drawdown halts)
7. Regime-caution posturing (risk-off → sit out)
8. Max positions per sleeve/worker

---

## 4. The anomaly-gating question — answered plainly

**Yes: every entry path in this system is anomaly-gated. There is no scheduled/baseline entry path.**

The only route to the LLM's consideration is: fire ≥2 change-detection signals → tier2a promotion → sleeve filter → top-15. The legacy scanner (a screener-style path) is disabled (`main.py:175-180`); the wheel worker is idle (no share positions); nothing enters on a calendar, a yield target, or a "the market is open and IV is adequate" basis. yield_farming — chartered as "the baseline-income sleeve" — has no baseline mechanism: it is an anomaly sleeve wearing an income sleeve's mandate, and its two config keys that pointed toward screening (`max_iv_rank`, `min_market_cap_proxy`) are dead.

**Consequence:** low trade volume is a *portfolio-design property*, not a defect of any single sleeve. Four sleeves waiting for four flavors of rare event will structurally under-produce a 50-decision experiment in 180 days, independent of every bug above. (Whether that's wrong is a charter question, per instruction not addressed here.)

---

## 5. The contaminated-feedback confound — quantified

```sql
SELECT COUNT(*) FROM cycle_snapshots
WHERE timestamp >= now() - interval '60 days' AND timestamp < '2026-07-09'
AND (reasoning LIKE '%win rate%' OR reasoning LIKE '%88%' OR reasoning LIKE '%44W%');
-- 93   (of 110 pre-repair-era cycles in the window)
```

**93 of 110 (85%) of pre-repair cycles carried the phantom-era performance stats in their reasoning context.** The agents didn't ignore them — they reasoned *from* them, in a specifically conservatism-inducing frame: the fabricated record showed a high win rate WITH net losses ("30-day win rate: 88% (44W/6L) — strong but the **-$1,956 total PnL shows losses have been outsized relative to wins**"). That is precisely the pattern that instructs a rational premium seller to tighten sizing and skip marginal setups. A material share of observed May–June conservatism is plausibly a *correct response to false data*. Post-repair cycles (Jul 9+) are the clean-baseline cohort — but only ~15 cycles exist so far, most also confounded by the truncation bug (fixed Jul 13, PR #5). **The uncontaminated, untruncated observation window effectively starts Jul 14.** Day-90/180 evaluations should treat pre-Jul-9 behavioral data as tainted for "was the system too conservative?" questions.

---

## 6. Dead pathways — the unused surface

| Pathway | Status | Evidence |
|---|---|---|
| **FRED macro** | ⚠️ Semi-alive | Read only inside `fundamentals_analyst.py:131-133` (macro context per fundamentals call). No regime/lead/sleeve consumption of the macro layer itself. |
| **EDGAR** | ✅ Alive | 355 cached fundamentals summaries in agent_messages; `get_fundamentals` tool wired and used. (Not dead — correcting the premise.) |
| `macro_news_events` (4,157 rows) | ❌ No reader found | Written via news pipeline; only `services/news_feed.py` references it (as writer). Grep finds no consumer. |
| `regime_confidence` | ❌ Dead | NULL on all 352 cycles; no writer passes it, no prompt reads it; advertised in chat schema doc (`chat_agent.py:41`) |
| `weight_overrides` (per-sleeve signal weights) | ❌ Dead | Accessor exists, zero callers — an entire designed personalization layer |
| `strategy_insights` table | ❌ Dead | 0 rows, no writer (known since July audit; prompt reference removed Jul 8, read-tool still wired) |
| `skill_documents` table | ❌ Dead | 0 rows; `research_data.update_skill_doc` has zero callers |
| `agent_capabilities` | ❌ Write-only | Startup upsert, no reader |
| `pending_changes` | ❌ Empty | 0 rows ever; no status-transition code |
| `proposals` human-in-the-loop API | ⚠️ Orphaned by UI | 9 endpoints live; the redesigned dashboard has no Trade Desk surface calling them (14 pending rows frozen since spring) |
| Redis (`settings.redis_url`) | ❌ Dead config | never used (known) |
| Legacy scanner + `universe_loader`/`universe_filters` | ❌ Disabled/dead | scheduled deletion per TIER_ARCHITECTURE step 6, still present |
| Wheel + Covered-Call workers | ⚠️ Dormant | wired and healthy but structurally unreachable (no share positions → no CC/wheel phase; all 11 entries were CSP) |

Sized: **two whole tables with zero writers, two with zero readers, one designed weighting layer never wired, six dead sleeve config keys, one dead API surface, and the macro-news corpus (4,157 rows) feeding nothing.**

---

*Per instruction: no fixes proposed, no configs touched. The classification in §3 is the actionable boundary — (a) items are integrity-neutral repairs, (b) items are design decisions, (c) items are charter territory.*
