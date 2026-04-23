# Backlog & Roadmap Integration Recon — Multi-Sleeve Architecture

Generated: 2026-04-23
Status: Recon only — no code changes

---

## Part 1: Backlog Item-by-Item Review

### Items Made Obsolete by Multi-Sleeve Architecture

| Item | Status | Reason for obsolescence |
|------|--------|------------------------|
| **1.4.2.10 Control Lead Agent** | Remove | The 4-sleeve experiment replaces this. Instead of a frozen baseline vs playbook-reading agent, we're comparing 4 distinct strategy sleeves against each other AND against a passive benchmark. The falsifiability is stronger: if no sleeve beats passive over 6 months, the thesis fails. |
| **TIER_ARCHITECTURE.md** | Archive | This document was written on April 9 as a "working hypothesis" for the tier funnel. The tier funnel is fully shipped. The multi-sleeve architecture supersedes this as the forward-looking design doc. Keep in git history, remove from repo root. |

### Items That Are Dependencies of Multi-Sleeve Work

| Item | Current Status | Dependency Relationship |
|------|---------------|------------------------|
| **1.4.2.1 Outcome labeler** | ✅ SHIPPED | **Critical.** Sleeves need labeled outcomes per-sleeve for the evaluation dashboard. Already shipped and running. |
| **1.4.2.2 Signal-weight learner** | ✅ SHIPPED | **Dependency.** Per-sleeve weight learning requires enough per-sleeve outcomes. The learner exists but needs a `sleeve_id` filter. ~5 lines to modify. |
| **1.4.1.1 Fundamentals Analyst** | ✅ SHIPPED | **Enhancer.** The Lead Agent calls get_fundamentals() when evaluating names. Works across all sleeves — sleeve-agnostic. No change needed. |
| **1.4.2.3 Research Analyst** | ✅ SHIPPED | **Enhancer.** Daily reflection should include per-sleeve observations ("event-driven sleeve dominated today's promotions"). Needs minor prompt update, not code change. |
| **1.4.2.4 Pre-market briefing** | ✅ SHIPPED | **Enhancer.** Briefing includes Research Analyst reflection. If reflection mentions sleeves, briefing automatically includes it. No change needed. |
| **1.4.3.1 Backtester** | ✅ SHIPPED | **Dependency.** Config backtester needs to support per-sleeve config comparison. Currently compares two tier2a.yaml files — would need to compare per-sleeve configs. ~30 lines to modify. |
| **1.5 Research Inspector** | ✅ SHIPPED | **Enhancer.** `/research` routes need a `/research/experiment` page showing per-sleeve metrics. The existing infrastructure (views, CLI, HTML routes) extends naturally. |

### Items That Are Orthogonal (Unaffected)

| Item | Notes |
|------|-------|
| **1.4.1.4 Prompt caching** | Still valuable, now more urgent (see cost analysis below). Orthogonal to sleeves — benefits all LLM calls regardless. |
| **1.4.2.5 Citation tracking** | Playbook citation → outcome correlation. Works across sleeves. |
| **1.4.2.6 Decay and re-validation** | Playbook entry lifecycle. Sleeve-agnostic. |
| **1.4.2.8 Skill document producer** | Per-agent skill docs. Could add per-sleeve skill docs later. |
| **1.6 Cross-database context retrieval** | Even more valuable with sleeves — agents querying across sleeve contexts. |
| **Credential rotation** | Still needed. Orthogonal. |
| **Legacy dead code cleanup** | Still needed. Orthogonal. |
| **HistoricalBar reads consolidation** | Still valuable. Orthogonal. |

### Items That Become More Valuable Once Sleeves Exist

| Item | Why more valuable |
|------|-------------------|
| **1.4.2.2 Signal-weight learner** | Per-sleeve weight optimization — different sleeves may weight the same signals differently. The learner becomes the mechanism for sleeve specialization. |
| **1.4.3 Validation pipeline** | Every sleeve config change needs backtesting. The pipeline becomes the gatekeeper for the entire experiment's integrity. |
| **1.5 Research Inspector** | The evaluation dashboard IS the research inspector for the experiment. `/research/experiment` is the critical new page. |
| **Phase 2 Dashboard** | The experiment needs real-time per-sleeve monitoring. This partially pulls Phase 2 forward. |

---

## Part 2: Phase Mapping

### Where does multi-sleeve fit?

The multi-sleeve architecture is **Phase 1.5** — it sits between the current Phase 1 (Data Foundation, which is ~95% complete) and Phase 2 (Real Dashboard). It's the transition from "build the substrate" to "run the experiment that validates the thesis."

### Phase 1 subtask relevance

| Subtask | Status | Relevance to sleeves |
|---------|--------|---------------------|
| 1.1 Research data layer | ✅ Complete | Foundation — unchanged |
| 1.2 Tiered scanning | ✅ Complete | Foundation — Tier 2a feeds all sleeves equally |
| 1.2b Historical bars | ✅ Complete | Foundation — unchanged |
| 1.3 Data feeds | ✅ Complete | Foundation — unchanged, but sleeves 3/6/9 may need new signals computed from existing feeds |
| 1.4.0b-a Tier 2a | ✅ Complete | **Needs robust stats migration** before sleeves launch. The 81.7% IV rank delta fire rate contaminates all sleeve scanners. |
| 1.4.0b-b Tier 2b | ✅ Complete | Foundation — Llama reasoning feeds all sleeves |
| 1.4.0c Lead Agent rewiring | ✅ Complete | **Needs sleeve-aware context** — the Lead Agent reads top 50 from one combined Tier 2 list. With sleeves, it needs per-sleeve top-N. |
| 1.4.1 Fundamentals Analyst | ✅ Complete | Sleeve-agnostic, works as-is |
| 1.4.2.1-4 Learning loop | ✅ Complete | Foundation — needs `sleeve_id` tagging |
| 1.4.2.2 Signal learner | ✅ Complete | Needs per-sleeve mode |
| 1.4.3 Validation pipeline | ✅ Complete (partial) | Needs per-sleeve config comparison |
| 1.5 Research Inspector | ✅ Complete | Needs `/research/experiment` page |

### Does Phase 2 get pulled forward?

**Partially yes.** The experiment evaluation dashboard overlaps with Phase 2's scope. But it's a focused subset — not the full "Real Dashboard" redesign. The recommendation:

- Build `/research/experiment` as an extension of the existing `/research` HTML routes (Phase 1.5 work)
- Defer the full React dashboard redesign (Phase 2 proper) until the experiment produces enough data to know what the dashboard should show
- The HTML `/research/experiment` page is the experiment's monitoring interface for 6 months. If the experiment succeeds, Phase 2 builds the production dashboard informed by what operators actually looked at.

### Does the sleeve abstraction help Phase 3 (architecture transferability)?

**Yes, significantly.** Phase 3's goal is extracting the four-tier funnel as a reusable framework for BTC perpetuals and prediction markets. The sleeve abstraction IS the framework:

- Each "market" (options, BTC perps, prediction markets) becomes a sleeve
- The Lead Agent, signal pipeline, learning loop, and risk framework work identically across markets
- The only per-market differences: data feeds, broker abstraction, and strategy parameters
- Building sleeves for options strategies proves the multi-strategy abstraction works before we add non-options markets

**The sleeve architecture makes Phase 3 a configuration exercise rather than an engineering project.**

---

## Part 3: Updated Roadmap Proposal

### Phase 1.5: Multi-Sleeve Experiment (Weeks 1-26)

#### Weeks 1-2: Infrastructure

| Task | Est. | Description |
|------|------|-------------|
| Robust stats migration | 1 day | Median/MAD for rules 1, 2, 3, 4, 7 in signal_compute.py. Backward-compatible (both metrics stored). |
| Sleeve abstraction | 1 day | `sleeve_id` migration on name_observations + trade_outcomes. SleeveConfig dataclass. Per-sleeve YAML configs. |
| Risk framework | 2 days | SleeveRiskGate service. Sector lookup. Greek aggregation. Hard limits table from recon Section 4. |
| 4 sleeve configs | 1 day | YAML configs for event-driven, vol-reversion, sector-rotation, yield-farming. Scanner criteria, weights, capital allocation. |
| Lead Agent sleeve awareness | 1 day | System prompt update + per-sleeve top-N tool. Edge estimate capture (not acted upon). |
| Experiment dashboard | 2 days | `/research/experiment` HTML page. Per-sleeve Sharpe, drawdown, win rate, correlation. |
| EXPERIMENT_CHARTER.md | Zane writes | Pre-registered criteria, termination rules, falsification conditions. |

#### Weeks 3-4: Launch + Stabilize

| Task | Est. | Description |
|------|------|-------------|
| Paper experiment launch | 1 day | $500K notional ($125K/sleeve), start date recorded in charter |
| First-week monitoring | Ongoing | Daily review of `/research/experiment`, manual sanity checks |
| Prompt caching | 1 day | Anthropic cache_control on system prompt + tool definitions. ~40% cost reduction on Lead Agent. |
| Bug fixes from real operation | Buffer | 2-3 days buffer for issues that surface in the first week |

#### Weeks 5-26: Run + Observe (minimal code changes)

**On hold during the experiment:**
- No new sleeves added
- No signal weight changes without backtester validation
- No architectural changes to the pipeline
- Daily monitoring via `/research/experiment`
- Monthly signal-weight learner runs (per-sleeve)
- Research Analyst captures per-sleeve patterns daily

**Allowed during the experiment:**
- Bug fixes to existing infrastructure
- Data quality improvements (e.g., coverage floor alerts)
- Research Inspector enhancements
- Backlog items marked "orthogonal"

#### Day 180: Evaluation Gate

Based on experiment outcomes:
- **If 2+ sleeves have Sharpe > 1.0 with drawdown < 8%:** Proceed to live deployment with top 2 sleeves at $12.5K each ($25K total)
- **If 1 sleeve has Sharpe > 1.0:** Live deploy that sleeve alone at $25K; continue paper on others
- **If 0 sleeves have Sharpe > 1.0:** Either extend experiment 90 days with parameter adjustments, or revise the thesis
- **If any sleeve has Sharpe < 0 after 90 days:** Terminate that sleeve, reallocate paper capital

#### Post-Day-180: Phase 2+ (conditional)

| Phase | Trigger | Scope |
|-------|---------|-------|
| **Phase 2: Production Dashboard** | At least 1 sleeve going live | Real-time per-sleeve monitoring, mobile-friendly, alerts |
| **Phase 3: Architecture Transfer** | 2+ sleeves profitable for 3 months | Extract sleeve framework, add BTC perpetuals market |
| **Phase 4a: Ensemble** | Live capital deployed | Second-opinion model on trade decisions where sleeve capital exceeds $10K |
| **Phase 4b: Kelly Sizing** | 100+ edge estimates with outcome labels | Enable edge-weighted sizing using calibrated LLM estimates |

---

## Part 4: Follow-up Questions

### Multi-leg order support: what does it unlock beyond Sleeve 4?

**It unlocks 4 capabilities:**

1. **Credit spreads** (Sleeve 4) — defined-risk, capital-efficient. The most important unlock.
2. **Iron condors** — sell both sides simultaneously. Useful for yield farming sleeve (1) and vol reversion sleeve (5).
3. **Strangles/straddles** — pure vol-selling structures. Useful for sleeve 3 (IV vs realized) and sleeve 5 (vol reversion).
4. **Pairs structures** — simultaneous long + short on correlated names. Enables sleeve 10 (pairs/stat arb).

**Case for building now:** Multi-leg is pure infrastructure — it doesn't change business logic, just enables more trade structures. ~50 lines in `alpaca_broker.py`. The cost of deferring is that 3 of the 6 deferred sleeves (4, 9, 10) require it, plus the 2 active sleeves that could benefit from defined-risk structures (1, 5). **Recommend building it in Week 2 as infrastructure, but not activating sleeve 4 until the 4-sleeve experiment stabilizes.**

### Cost projection: 4 sleeves with and without prompt caching

**Without prompt caching (current):**
- Lead Agent: ~$1.50/cycle × 3 cycles × 22 days = **~$99/month** (Claude Sonnet)
- System prompt + tools: ~4,000 tokens, sent every turn of multi-turn loop (~5 turns/cycle)
- With 4 sleeves: context is ~40% larger (per-sleeve top-N lists) = **~$140/month**

**With prompt caching:**
- Anthropic's prompt caching: system prompt + tools cached for 5 minutes. First call: full price. Subsequent turns in same cycle: cached prefix at 90% discount.
- System prompt + tools = ~4,000 tokens × 4 turns cached = ~16,000 tokens saved per cycle at $0.30/M discount
- Savings: ~$0.05/cycle × 66 cycles/month = **~$3.30/month saved** (modest because the savings are on the cached prefix only)
- Bigger savings: if we cache the Tier 2 promotions list (which is the same for all turns within a cycle), savings increase to ~**$15-20/month**

**Implementation effort:** ~20 lines in `llm_service.py`. Add `cache_control: {"type": "ephemeral"}` to the system message block. Anthropic's SDK handles the rest. **Ship in Week 3 after launch stabilizes.**

### Robust statistics: backward-compatible or cutover?

**Backward-compatible.** The approach:

1. Add `_safe_median()` and `_safe_mad()` alongside existing `_safe_mean()` and `_safe_std()`
2. Each rule function computes BOTH: `z_mean_std` (current) and `z_median_mad` (new)
3. Signal output includes both: `{"score": 0.25, "raw_zscore": 2.1, "robust_zscore": 2.8, ...}`
4. The composite score uses the robust z-score; the old z-score is preserved in the analysis JSON for comparison
5. After 30 days of dual-mode data, the signal-weight learner can evaluate which predicts outcomes better

**Impact on existing 23 pre-funnel outcomes:** These were labeled against the old scoring. They remain valid for the old z-scores but meaningless for the new robust z-scores. The signal-weight learner's 50-sample gate handles this — it won't retrain on robust scores until enough new labeled outcomes accumulate.

### Lead Agent: one instance across 4 sleeves or per-sleeve instances?

**One Lead Agent, reasoning across all 4 sleeves.**

Reasons:
- **Cross-sleeve awareness matters.** If the event-driven sleeve and vol-reversion sleeve both want to sell puts on NVDA, the Lead Agent needs to see both to avoid concentration. Per-sleeve instances can't do this.
- **Cost.** 4 Claude instances × $99/month = $396/month. One instance at $140/month saves $256/month.
- **Consistency.** One agent means one playbook, one reasoning style, one learning trajectory.

The risk is context window pressure. Mitigation: instead of 50 names from one combined list, serve 15 per sleeve (60 total). The Lead Agent's prompt explicitly structures reasoning by sleeve: "For each sleeve, review its top candidates and decide."

### Pre-registration: EXPERIMENT_CHARTER.md template

```markdown
# Premium Trader — Multi-Sleeve Experiment Charter

## Experiment ID: [auto-generated]
## Start Date: [YYYY-MM-DD]
## End Date: [Start + 180 trading days]
## Registered By: [name]

## Hypothesis
[What the experiment is testing — one sentence]

## Sleeves

### Sleeve 1: [Name]
- **Strategy:** [one-paragraph description]
- **Capital allocation:** $[amount]
- **Max concurrent positions:** [N]
- **Success criteria:** [Sharpe > X, drawdown < Y%, win rate > Z%]

[Repeat for each sleeve]

## Evaluation Criteria

### Per-sleeve success (Day 180)
- [ ] Sharpe ratio > [threshold]
- [ ] Max drawdown < [threshold]%
- [ ] Win rate > [threshold]%
- [ ] At least [N] closed trades

### Portfolio-level success
- [ ] Combined Sharpe > [threshold]
- [ ] Cross-sleeve correlation < [threshold]
- [ ] Total cost < $[threshold]/month

## Termination Rules

### Capital preservation (automatic)
- Sleeve hits -[X]% drawdown → pause, human review required to restart
- Portfolio hits -[X]% drawdown → halt all new positions across all sleeves

### Performance evaluation (Day 90 checkpoint)
- Sleeve with Sharpe < [threshold] after 90 days → [action: terminate / extend / adjust]

## Falsification Conditions
What would prove the multi-sleeve thesis wrong:
- [ ] [condition 1]
- [ ] [condition 2]

## Scaling Triggers (post-Day-180)
- Sleeve qualifies for live capital if: [criteria]
- Initial live allocation: $[amount] per qualifying sleeve
- Capital increase schedule: [rules]

## Data Collection Requirements
- [ ] Per-sleeve daily PnL logged
- [ ] Per-sleeve Sharpe computed rolling 20-day
- [ ] Pairwise sleeve correlations computed daily
- [ ] Edge estimates captured (not acted upon)
- [ ] All trades tagged with sleeve_id

## Prohibited Changes During Experiment
- [ ] No new sleeves added
- [ ] No signal weight changes without backtester validation
- [ ] No architectural changes to the pipeline
- [ ] Allowed: bug fixes, data quality, monitoring enhancements
```

---

## Part 5: Summary — What Ships When

### Week 1-2 (Infrastructure)
1. Robust stats migration (signal_compute.py)
2. Sleeve abstraction (migration + configs + Risk Gate)
3. Lead Agent sleeve awareness
4. Multi-leg order support (infrastructure, not activated)
5. Experiment dashboard (`/research/experiment`)

### Week 3-4 (Launch)
6. Prompt caching (llm_service.py)
7. EXPERIMENT_CHARTER.md filled out by Zane
8. Paper experiment launches Day 1
9. First-week stabilization

### Weeks 5-26 (Run — minimal code changes)
- Daily: Research Analyst captures per-sleeve observations
- Monthly: Signal-weight learner per-sleeve
- As needed: Bug fixes, data quality
- On hold: Everything else

### Day 180 (Evaluation)
- Evaluate per EXPERIMENT_CHARTER.md criteria
- Decision: live deploy top sleeves, extend, or revise thesis

### Post-experiment
- Phase 2: Production dashboard (if live deploying)
- Phase 3: Architecture transfer to BTC perps (if sleeves work)
- Phase 4b: Kelly sizing (after edge estimate calibration)
