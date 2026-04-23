# Premium Trader — Multi-Sleeve Experiment Charter

## Experiment ID: [auto-generated at launch]
## Start Date: [YYYY-MM-DD]
## End Date: [Start + 180 calendar days]
## Registered By: [name]

---

## Hypothesis

[What the experiment is testing — one sentence]

---

## Sleeves

### Sleeve 1: Event-Driven Premium
- **Strategy:** [one-paragraph description]
- **Capital allocation:** $125,000
- **Max concurrent positions:** 5
- **Success criteria:**
  - [ ] Sharpe ratio > [threshold]
  - [ ] Max drawdown < [threshold]%
  - [ ] Win rate > [threshold]%
  - [ ] At least [N] closed trades

### Sleeve 2: Vol Mean Reversion
- **Strategy:** [one-paragraph description]
- **Capital allocation:** $125,000
- **Max concurrent positions:** 5
- **Success criteria:**
  - [ ] Sharpe ratio > [threshold]
  - [ ] Max drawdown < [threshold]%
  - [ ] Win rate > [threshold]%
  - [ ] At least [N] closed trades

### Sleeve 3: Sector Rotation Premium
- **Strategy:** [one-paragraph description]
- **Capital allocation:** $125,000
- **Max concurrent positions:** 6
- **Success criteria:**
  - [ ] Sharpe ratio > [threshold]
  - [ ] Max drawdown < [threshold]%
  - [ ] Win rate > [threshold]%
  - [ ] At least [N] closed trades

### Sleeve 4: Yield-Farming Premium
- **Strategy:** [one-paragraph description]
- **Capital allocation:** $125,000
- **Max concurrent positions:** 8
- **Success criteria:**
  - [ ] Sharpe ratio > [threshold]
  - [ ] Max drawdown < [threshold]%
  - [ ] Win rate > [threshold]%
  - [ ] At least [N] closed trades

---

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

---

## Termination Rules

### Capital preservation (automatic)
- Sleeve hits -[X]% drawdown → pause, human review required to restart
- Portfolio hits -[X]% drawdown → halt all new positions across all sleeves

### Performance evaluation (Day 90 checkpoint)
- Sleeve with Sharpe < [threshold] after 90 days → [action: terminate / extend / adjust]

---

## Falsification Conditions

What would prove the multi-sleeve thesis wrong:
- [ ] [condition 1]
- [ ] [condition 2]
- [ ] [condition 3]

---

## Scaling Triggers (post-Day-180)

- Sleeve qualifies for live capital if: [criteria]
- Initial live allocation: $[amount] per qualifying sleeve
- Capital increase schedule: [rules]

---

## Data Collection Requirements

- [ ] Per-sleeve daily PnL logged
- [ ] Per-sleeve Sharpe computed rolling 20-day
- [ ] Pairwise sleeve correlations computed daily
- [ ] Edge estimates captured (not acted upon during Phase 1)
- [ ] All trades tagged with sleeve_id
- [ ] All name_observations tagged with sleeve_id
- [ ] Config versioning on all observations

---

## Prohibited Changes During Experiment

- [ ] No new sleeves added
- [ ] No signal weight changes without backtester validation
- [ ] No architectural changes to the pipeline
- [ ] Allowed: bug fixes, data quality improvements, monitoring enhancements, prompt tuning within sleeves

---

## Review Schedule

- Day 30: First data review. Are all sleeves producing trades? Any data quality issues?
- Day 60: Interim performance check. Any sleeves clearly non-viable?
- Day 90: Formal checkpoint per termination rules above.
- Day 120: Mid-experiment review. Adjust any sleeves that are viable but underperforming?
- Day 180: Final evaluation per criteria above.
