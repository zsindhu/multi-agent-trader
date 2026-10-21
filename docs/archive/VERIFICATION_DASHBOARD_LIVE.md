# Live-Data Dashboard Verification — 2026-07-14

> **Archived snapshot (2026-07-14).** Still open as of 2026-10-21: the reconciliation `ok` gate
> can never pass (`services/broker_reconciliation.py:158` requires drift < $50 against a permanent
> ~$805 legacy drift), and the `?` funnel marker on TradesPage is over-applied. Tracked in BACKLOG.md.

Verification pass per operator instruction, run after today's 8:08 ET tier-1 sweep,
two tier-2 sweeps (10:05, 12:04 ET), and the first two post-fix Lead cycles.
Read-only; no code changed. "UI value" = the API response the dashboard renders
(the pages are thin clients over these endpoints; client-side derivations noted
where they exist).

---

## TOP LINE — checkpoint-critical status for the 19th

| # | Item | Status |
|---|------|--------|
| 1 | Funnel spine counts + sweep stamp | **PASS** — exactly latest-sweep, no multiplication, stamp matches to the second |
| 2 | Learning progress vs learner math | **PASS** — UI ≡ learner exactly. **But the honest number is 2/50, not 4/50** (see correction) |
| 3a | Snapshot + sleeve coverage gate (≥90%) | **PASS — 100% / 100%** (5/5 entries since Jul 12, including this morning's live trades) |
| 3b | Reconciliation-green gate (≥95% of days) | **FAILING BY CONSTRUCTION — 0/2 days green.** Not a dashboard bug: `report.ok` requires \|drift\| < $50, and the $805 legacy drift (runaway-XLV buys, permanently unattributable to outcomes) makes every future report red regardless of daily health. **The charter gate as written can never pass. Decision needed before the 19th: baseline the legacy drift or redefine `ok` as day-over-day drift delta.** |

One correction I owe: my Jul 11–13 documents (and charter amendment A3) reported "clean n = 4." That counted clean *outcomes* (UNP + CRM×3). The learner counts *decisions* — CRM's three contracts share one observation — so the true count is **2**. The dashboard is right; my earlier reports were wrong. A3 should be amended.

---

## Item 1 — Funnel spine (CHECKPOINT-CRITICAL): PASS

**UI** (`/api/dashboard/status`): `tier1_universe: 6476, tier2_promoted: 281, tier2_rejected: 4054`, `last_tier2_sweep: 2026-07-14T16:04:41Z` → spine renders "as of 12:04 sweep".

**DB**:
```sql
SELECT tier, COUNT(*), SUM(CASE WHEN was_considered THEN 1 ELSE 0 END)
FROM name_observations n WHERE timestamp>=CURRENT_DATE
AND sweep_id=(SELECT MAX(sweep_id) FROM name_observations
              WHERE tier=n.tier AND timestamp>=CURRENT_DATE) GROUP BY tier;
-- tier 1: 6476 rows | tier 2: 4335 rows, 281 considered
SELECT tier, COUNT(*) FROM name_observations WHERE timestamp>=CURRENT_DATE GROUP BY tier;
-- tier 1: 6476 | tier 2: 8670  (= 2 sweeps × 4335)
SELECT sweep_id, MAX(timestamp) FROM name_observations
WHERE tier=2 AND timestamp>=CURRENT_DATE GROUP BY sweep_id;
-- 20260714T140536… 14:05:42Z | 20260714T160438… 16:04:41Z
```
- Universe 6476 = 6476 ✓ (latest t1 sweep total scanned). Promoted 281 = 281 ✓. Rejected 4054 ✓ (281+4054 = 4335 = one sweep).
- **Multiplication check: today holds 8,670 tier-2 rows; the UI shows 4,335-sweep numbers, not 2×.** The Block-2 failure mode is absent.
- Stamp: UI `16:04:41Z` = MAX-sweep timestamp `16:04:41Z` ✓ (renders 12:04 ET). Pipeline page uses the same endpoint — same result.

## Item 2 — Learning progress (CHECKPOINT-CRITICAL): PASS (value = 2)

**UI**: `learning_progress: {samples: 2, clean: 2, unknown: 0, contaminated_excluded: 6, threshold: 50}`.

**DB (learner math, exactly)**:
```sql
SELECT COUNT(DISTINCT COALESCE(name_observation_id::text,'o'||id))
FROM trade_outcomes WHERE funnel_driven=true AND outcome IN ('win','loss')
AND id NOT IN (96,97,98,99,103,104);          -- 2
SELECT COUNT(*) FROM trade_outcomes WHERE funnel_driven IS NULL;  -- 0
```
UI 2/0 ≡ SQL 2/0 ≡ `SignalLearner._load_data` semantics (same dedup key, same exclusion set — the endpoint imports `CONTAMINATED_OUTCOME_IDS` from the learner class, so they cannot drift apart). The 3-state bar renders clean=2 navy, unknown=0, 48 empty.

## Item 3 — Reconciliation + coverage (CHECKPOINT-CRITICAL): SPLIT

**Coverage (charter gate: ≥90% from 2026-07-12)** — **PASS, 100%**:
```sql
SELECT COUNT(*), COUNT(signal_snapshot), COUNT(sleeve_id) FROM trades
WHERE trade_type IN ('sell_to_open','buy_to_open') AND created_at>='2026-07-12';
-- 5 | 5 | 5
```
The 5: BABA×3 (Jul 13, `yield_farming`, obs-linked) and **HLT×2 (today 10:33 ET, `event_driven`, `signal_snapshot` populated, `name_observation_id` 1818027)** — freeze-at-decision proven on live production trades, not just the harness.

**Reconciliation-green (charter gate: ≥95% of days)** — **0/2, failing by construction**:
```sql
SELECT DATE(timestamp), payload::jsonb->>'ok', payload::jsonb->>'discrepancy_count',
       payload::jsonb->>'pnl_drift' FROM agent_messages
WHERE message_type='reconciliation_report' AND timestamp>='2026-07-12' ORDER BY 1;
-- 2026-07-12 | false | 0 | 805.0
-- 2026-07-13 | false | 3 | 805.0
```
- The Jul 13 discrepancies were 3 × `status_mismatch` on the BABA orders (db `submitted` vs broker `expired` — the nightly report ran between broker EOD expiry and the next morning's reconciler). **Self-healed**: all three are `order_expired` in the DB as of this morning's cycle-start reconcile. Tonight's count should be 0.
- The $805 drift is the permanent legacy gap (labeled +$701 vs broker −$104; the runaway-XLV excess buys belong to no entry decision) and `ok` requires \|drift\| < $50 → **every report is red forever**. The panel displays this truthfully ("N ISSUES"); the *charter gate* is what's broken. Needs an operator decision, not a code fix (per instructions, none made).

## Item 4 — Sleeve scorecard: PASS (sparse-because-correct)

**UI** (`/trades` `summary.by_sleeve`): single bucket `unattributed: {trades: 17, …}`.
```sql
SELECT COALESCE(o.sleeve_id, t.sleeve_id, 'unattributed'), COUNT(*)
FROM trade_outcomes o JOIN trades t ON t.id=o.trade_id
WHERE o.outcome IN ('win','loss','breakeven') GROUP BY 1;   -- unattributed | 17
```
All 17 labeled outcomes predate sleeve attribution (Jul 12) → one honest bucket. **The read path works**: today's HLT rows carry `event_driven` and the endpoint's fallback chain (`outcome.sleeve_id ?? trade.sleeve_id`) will bucket them on labeling. "No data yet," not "data not read."

## Item 5 — Envelope cards (post-fix): PASS, with one operational incident

```sql
SELECT id, actions_decided, llm_cost_usd,
 (SELECT COUNT(*) FROM jsonb_each(full_context::jsonb->'sleeve_envelopes') e
  WHERE e.value->>'degraded'='false') AS ok_envs, … FROM cycle_snapshots
WHERE timestamp>=CURRENT_DATE;
-- 354 | 2 | $1.52 | 4 ok, 0 degraded     ← first post-fix cycle
-- 355 | 0 | $0.00 | 0 envelopes          ← ALL sleeves "LLM API error — safe mode"
SELECT MAX(tokens_out), COUNT(*) FILTER (WHERE tokens_out=4096)
FROM llm_usage_log WHERE timestamp>=CURRENT_DATE;   -- 13720 | 0
```
- **Cycle 354: 4/4 envelopes parsed (verdict/confidence/factors), zero degraded, and 2 real actions — the HLT entries.** Yesterday: 1/12. Max output today 13,720 tokens — above the old 4,096 ceiling (i.e., yesterday this cycle would have been truncated), zero cap hits. `/cycles` serves the envelope fields; the card renders the real state, not the degraded fallback. **Block 3 prompts land; PR #5 confirmed in production.**
- Cycle 355 (12:20 ET): Together API failure across all four sleeves; safe-mode fallback engaged correctly, $0 spent, honestly rendered. Operational note — if the 14:20 cycle repeats this, investigate Together account status; not a dashboard defect.

## Item 6 — Three-state funnel column: PASS on the spec, PARTIAL on semantics

```sql
SELECT CASE WHEN o.id IS NULL THEN 'no_outcome(?)'
            WHEN o.funnel_driven IS NULL THEN 'null(?)'
            WHEN o.funnel_driven THEN 'true(✓)' ELSE 'false(blank)' END, COUNT(*)
FROM trades t LEFT JOIN trade_outcomes o ON o.trade_id=t.id GROUP BY 1;
-- true(✓) 10 | false(blank) 7 | no_outcome(renders ?) 145
```
- The spec's must — "post-cutover trade with no surviving evidence renders `?`, never blank" — **holds**; no labeled-unknown row can render blank (`value===true→✓, ===false→blank, else ?`), and the funnel-only filter excludes both null and false (`TradesPage.jsx:142`).
- **Finding (reported, not fixed):** the `?` is over-applied — all 145 outcome-less rows get it, including buy-to-close exit legs and unfilled orders that will *never* be labeled. `?` currently means "no outcome row," not specifically "post-cutover, evidence lost." Dilutes the marker; a one-line refinement once approved.

## Item 7 — Fill quality / slippage math: PASS (no samples yet, honestly reported)

**UI** (`/fill-quality`, 30d): `entry_orders: 7, filled: 1, fill_rate_pct: 14.3, avg_slippage: null, slippage_samples: 0`.
```sql
SELECT COUNT(*), COUNT(*) FILTER (WHERE status IN ('filled','partially_filled','closed','assigned'))
FROM trades WHERE trade_type='sell_to_open' AND created_at >= now()-interval '30 days';
-- 7 | 1   (XLC×2 Jun 22, BABA×3 Jul 13, HLT×2 today; only Jun-22 XLC filled)
```
7→14.3% ✓. Slippage null is correct: no fill has both `premium` and `fill_price` yet (the column postdates all fills). Broker cross-check on the one recent close-side fill: XLC sold 4 @ 0.20 at Alpaca ≡ `trades.price 0.20` ✓. The first HLT fill will produce the first real slippage sample.

## Item 8 — Every panel, categorized

**Real data, verified:** funnel spine (both pages) · learning progress · equity chart (6 of 8 recent days have snapshots) · sleeves P&L + scorecard (unattributed bucket) · positions table · agent activity terminal (live sweep/cycle events) · promotions table — 50 rows, **50/50 with tier2b reasoning** (write-once columns working) · signal fire rates · scan schedule (real timestamps) · daily P&L · reflection (prose; structured block starts with tonight's run) · envelope cards · reconciliation panel (truthfully red) · integrity window · per-agent cost (today’s 4 sleeves; MTD $55.14 of $150 → projection ~$118, under budget) · message bus (fundamentals traffic) · chat latency (per-session, live).

**Honest empty states, confirmed empty-because-empty:** conflicts (0 in 7d — none have occurred), near-misses (no API, labeled as such), DB write audit / overwrite diffs (Integrity Sentinel not built, says so), per-sleeve capital (`--`), slippage (no samples).

**Wrong numbers: none found.** Two semantic findings only: the over-broad `?` (item 6) and `report.ok` conflating legacy drift with daily health (item 3b) — both reported above, neither fixed per instructions.

---

## For the Day-90 checkpoint (2026-07-19)

- Gate "≥90% snapshot+sleeve coverage from Jul 12": **PASS at 100%** and structurally enforced.
- Gate "reconciliation green ≥95% of days": **needs redefinition before it can measure anything** — proposal required (baseline the $805, or gate on drift *delta*).
- Learning progress: **2/50 clean decisions** (charter A3's "4" should be amended to 2 — outcomes vs decisions).
- The clean observation window (uncontaminated stats + untruncated envelopes + weekend gates) is now fully live as of cycle 354. Today already produced 2 attributed, snapshot-carrying entry orders — the funnel-throughput question from the two constraint audits remains the binding issue for the 50-decision threshold.
