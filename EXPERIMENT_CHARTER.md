# Premium Trader — Multi-Sleeve Experiment Charter

## Experiment ID: MSE-2026-01
## Start Date: 2026-04-20 (funnel cutover — registered retroactively 2026-07-11, see Amendments)
## End Date: 2026-10-17 (Start + 180 calendar days)
## Registered By: Zane Sindhu (operator), drafted by Claude Code from live config

> **Registration note (honesty clause):** this charter was registered on
> 2026-07-11, ~12 weeks into the experiment window, after the July audits
> found it had been left as an unfilled template. All facts (sleeves,
> capital, dates, amendments) are from live config and DB. All success
> thresholds are marked **[PROPOSED]** — they were drafted at registration,
> not pre-committed at start, and the Day-180 evaluation must weight that
> accordingly. Operator should confirm or amend the [PROPOSED] values.

---

## Hypothesis

An LLM-orchestrated multi-sleeve options-premium system, fed by a mechanical
signal funnel with full decision transparency, can (a) generate repeatable
risk-adjusted returns in at least one sleeve, and (b) produce labeled
decision data of sufficient quality to statistically validate which signals
carry edge.

---

## Sleeves (from config/sleeves/*.yaml, live since ~2026-04-23)

### Sleeve 1: Event-Driven Premium (`event_driven`)
- **Strategy:** Sell CSPs into elevated IV before earnings (delta −0.20, 7–21 DTE), close 1 day before the event.
- **Capital allocation:** $125,000
- **Max concurrent positions:** 5
- **Success criteria (Day 180):**
  - [ ] Sharpe ratio > 1.0 **[PROPOSED]**
  - [ ] Max drawdown < 10% of sleeve capital **[PROPOSED]**
  - [ ] Win rate > 60% **[PROPOSED]**
  - [ ] At least 15 closed trades **[PROPOSED]**

### Sleeve 2: Vol Mean Reversion (`vol_reversion`)
- **Strategy:** Sell premium into unexplained IV spikes (high IV rank, low news density).
- **Capital allocation:** $125,000
- **Max concurrent positions:** per config
- **Success criteria:** same thresholds as Sleeve 1 **[PROPOSED]**

### Sleeve 3: Sector Rotation Premium (`sector_rotation`)
- **Strategy:** Sell premium on sector ETFs with macro-driven IV; sole claimant for ETF conflicts.
- **Capital allocation:** $125,000
- **Max concurrent positions:** per config
- **Success criteria:** same thresholds as Sleeve 1 **[PROPOSED]**

### Sleeve 4: Yield-Farming Premium (`yield_farming`)
- **Strategy:** Far-OTM CSPs/CCs on stable large-caps, moderate IV rank; the baseline-income sleeve.
- **Capital allocation:** $125,000
- **Max concurrent positions:** per config
- **Success criteria:** same thresholds as Sleeve 1 **[PROPOSED]**

---

## Evaluation Criteria

### Per-sleeve success (Day 180)
As above, per sleeve. Evaluation MUST segment by protocol era (see
Amendments): labels before 2026-07-08 are known-contaminated; the lead-agent
model changed 2026-07-08.

### Portfolio-level success
- [ ] Combined Sharpe > 1.2 **[PROPOSED]**
- [ ] Mean pairwise sleeve correlation < 0.7 **[PROPOSED]**
- [ ] Total LLM + data cost < $150/month **[PROPOSED]**

### Learning-pipeline success (added at registration — this is the research thesis)
- [ ] ≥ 50 clean funnel-driven labeled decisions by Day 180 (signal-learner activation)
- [ ] Nightly broker reconciliation green ≥ 95% of days from 2026-07-12 onward
- [ ] ≥ 90% of entry trades carry signal_snapshot + sleeve attribution from 2026-07-12 onward

---

## Termination Rules

### Capital preservation (automatic)
- Sleeve hits −10% drawdown of sleeve capital → pause, human review required to restart **[PROPOSED]**
- Portfolio hits −8% drawdown → halt all new positions across all sleeves **[PROPOSED]**

### Performance evaluation (Day 90 checkpoint — 2026-07-19)
- Sleeve with Sharpe < 0 and ≥ 10 closed trades after 90 days → flag for review (not auto-terminate) **[PROPOSED]**

---

## Falsification Conditions

What would prove the multi-sleeve thesis wrong:
- [ ] No sleeve achieves Sharpe > 0 with ≥ 15 closed trades by Day 180
- [ ] The signal learner, once activated at n=50, finds no signal with a coefficient distinguishable from zero (edge is noise)
- [ ] Fill-rate + funnel throughput cannot produce 50 clean labeled decisions in 180 days even after remediation (the data engine, not the market, is the binding constraint)

---

## Scaling Triggers (post-Day-180)

- Sleeve qualifies for live capital if: Sharpe > 1.5 over the final 60 days with drawdown < 5% **[PROPOSED]**
- Initial live allocation: $12,500 per qualifying sleeve, max 2 sleeves **[PROPOSED]**
- Capital increase schedule: operator decision after 30 live days **[PROPOSED]**

---

## Data Collection Requirements

- [x] All trades tagged with sleeve_id — shipped 2026-07-11 (freeze-at-decision plumbing)
- [x] Signal snapshot frozen onto trades at decision time — shipped 2026-07-11
- [x] Edge estimates captured, not acted upon (`edge_estimate_captured` actions)
- [x] Conflict-resolution verdicts persisted — shipped 2026-07-11
- [x] Config versioning on observations (`analysis.config_version`)
- [x] Model identifier per cycle (`cycle_snapshots.llm_model`)
- [ ] Per-sleeve daily PnL logged (needs sleeve-tagged outcomes to accumulate)
- [ ] Per-sleeve rolling Sharpe + pairwise correlations (blocked on above)

---

## Prohibited Changes During Experiment

- No new sleeves added
- No signal weight changes without backtester validation (learner output is a PROPOSAL until validated)
- No architectural changes to the tier funnel
- Allowed: bug fixes, data-quality/integrity improvements, monitoring, prompt tuning within sleeves

---

## Amendments (protocol deviations, recorded per working rule 1)

| # | Date | Change | Impact on evaluation |
|---|------|--------|----------------------|
| A1 | 2026-07-08 | **Outcome-data repair**: 87 contaminated labels purged and relabeled from fills (phantom expired-order wins; see RECON_PRE_REMEDIATION_VERIFICATION.md Q2). | All current labels are post-repair artifacts; pre-repair metrics are void. |
| A2 | 2026-07-08 | **Lead-agent model switch**: claude-sonnet-4-6 → zai-org/GLM-5.2 (commit 4a92b26), same deploy as A1. | Decisions ≤ 2026-07-07 are Sonnet-era; ≥ 2026-07-08 GLM-era. Model and label-quality effects are **confounded at this boundary** — segment analyses must not attribute cross-boundary deltas to the model alone. |
| A3 | 2026-07-11 | **Structured-data remediation** (Blocks 1–3): freeze-at-decision snapshots, append-only sweeps, bounded labeler fallback, judgment envelopes, learner counts decisions not contracts, 6 wrong-sweep labels (outcome ids 96–99, 103, 104) excluded from training. | Clean-label era begins 2026-07-12. Effective clean n at registration: 4. |
| A4 | 2026-07-11 | **Charter registered retroactively** with [PROPOSED] thresholds. | Day-180 evaluation treats thresholds as drafted-at-week-12, not pre-registered. |

---

## Review Schedule

- Day 30 (2026-05-20): missed — charter not registered. Covered retroactively by the 2026-07-07 audit.
- Day 60 (2026-06-19): missed — same.
- Day 90 (2026-07-19): **first live checkpoint.** Data-quality gates (reconciliation green, snapshot/sleeve coverage) + sleeve viability review.
- Day 120 (2026-08-18): mid-experiment review.
- Day 180 (2026-10-17): final evaluation per criteria above, segmented per A2.
